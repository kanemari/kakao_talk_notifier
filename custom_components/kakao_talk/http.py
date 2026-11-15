import json
import logging
import os
import secrets
import time
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlencode

import aiohttp
import voluptuous as vol
from aiohttp import web
from homeassistant.components import persistent_notification
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.notify import ATTR_TITLE
from homeassistant.core import ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import is_cloud_connection
from homeassistant.util.network import is_local

from .const import (
    ATTR_URL,
    CONF_API_KEY,
    CONF_BUTTON_TITLE,
    CONF_CLIENT_SECRET,
    CONF_FRIENDS,
    CONF_LINK_URL,
    CONF_REDIRECT_URI,
    CONF_SEND_TO_FRIENDS,
    DOMAIN,
    KAKAO_TALK_API_ENDPOINT,
    SERVICE_LIST_FRIENDS,
    SERVICE_LOGIN,
    SERVICE_SEND_MESSAGE,
    SESSION_FILE,
)

_LOGGER = logging.getLogger(__name__)

COMPONENT_DIR = Path(__file__).parent
IMAGES_DIR = COMPONENT_DIR / "images"
SETUP_PAGE = COMPONENT_DIR / "setup.html"

OAUTH_AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
OAUTH_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
API_MEMO_SEND = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
API_FRIENDS = "https://kapi.kakao.com/v1/api/talk/friends"
API_FRIENDS_SEND = "https://kapi.kakao.com/v1/api/talk/friends/message/default/send"

FRIENDS_PAGE_SIZE = 100
# Kakao limits the number of receivers per friends-message request.
FRIENDS_SEND_CHUNK = 5
# How long the friends list is cached before it is fetched again.
FRIENDS_CACHE_SECONDS = 3600

DEFAULT_BUTTON_TITLE = "View"

# How long a started login stays valid, in seconds.
LOGIN_STATE_SECONDS = 600
# Only this many started logins are remembered at once.
MAX_LOGIN_STATES = 5
LOGIN_NOTIFICATION_ID = "kakao_talk_login"


def _is_local_request(hass, request):
    """True if the request appears to come from the local network.

    This is defence in depth only: behind a reverse proxy that hides the client
    address every request looks local. The real protection is that a login can
    only be started by an authenticated Home Assistant admin (see the login action).
    """
    if is_cloud_connection(hass):
        return False
    try:
        return is_local(ip_address(request.remote))
    except (TypeError, ValueError):
        return False


def _write_private(path, content):
    """Write a file readable only by the Home Assistant user."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(content)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _read_text(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as file:
        return file.read()


def _read_session(path):
    if not os.path.exists(path) or os.stat(path).st_size == 0:
        return None
    return _read_text(path).strip() or None


class KakaoConfig:
    def __init__(self, hass, config):
        self.hass = hass
        self._api_key = config.get(CONF_API_KEY)
        self._client_secret = config.get(CONF_CLIENT_SECRET)
        self._button_title = config.get(CONF_BUTTON_TITLE) or DEFAULT_BUTTON_TITLE
        self._host = config.get(CONF_REDIRECT_URI)
        # URL that message buttons link to; its domain must be registered at Kakao.
        self._link_url = config.get(CONF_LINK_URL) or self._host
        self._login_states = {}
        self._send_to_friends = config.get(CONF_SEND_TO_FRIENDS)
        # Optional filter: nicknames or uuids to send to. Empty means everyone returned.
        self._friend_filter = [str(f).strip().lower() for f in config.get(CONF_FRIENDS) or []]
        self._friends = []  # list of {"uuid": ..., "nickname": ...}
        self._friends_fetched = 0.0
        self._access_token = None
        self._refresh_token = None

        _LOGGER.debug("KakaoConfig %s", self._host)
        hass.async_create_task(self._load_session())

    # ------------------------------------------------------------------ session
    async def _load_session(self):
        path = self.hass.config.path(SESSION_FILE)
        token = await self.hass.async_add_executor_job(_read_session, path)
        if token:
            self._refresh_token = token
        else:
            _LOGGER.warning("Not logged in to KakaoTalk yet; run the kakao_talk.login action")

    async def save_refresh_token(self):
        path = self.hass.config.path(SESSION_FILE)
        try:
            await self.hass.async_add_executor_job(
                _write_private, path, self._refresh_token
            )
        except OSError as exception:
            _LOGGER.error("Error saving refresh token: %s", exception)

    async def get_setup_page(self):
        try:
            return await self.hass.async_add_executor_job(_read_text, SETUP_PAGE)
        except OSError as exception:
            _LOGGER.error("Error reading setup.html: %s", exception)
            return ""

    # ------------------------------------------------------------------ OAuth
    def redirect_uri(self):
        """The OAuth redirect URI; must match the one registered at Kakao.

        Built only from configuration, never from the incoming request, so a
        forged Host header cannot change where Kakao sends the login.
        """
        return self._host.rstrip("/") + KAKAO_TALK_API_ENDPOINT

    def new_login_state(self):
        """Create a single-use token tying the Kakao callback to a login we started."""
        now = time.monotonic()
        live = sorted(
            ((t, s) for s, t in self._login_states.items() if t > now), reverse=True
        )
        # Keep only the newest few so the store cannot grow without bound.
        self._login_states = {s: t for t, s in live[: MAX_LOGIN_STATES - 1]}
        state = secrets.token_urlsafe(32)
        self._login_states[state] = now + LOGIN_STATE_SECONDS
        return state

    def consume_login_state(self, state):
        expires = self._login_states.pop(state or "", 0)
        return expires > time.monotonic()

    def authorize_url(self):
        """Kakao login URL for a new login. Only hand this to an authenticated admin."""
        scope = "talk_message"
        if self._send_to_friends:
            scope += ",friends"
        return OAUTH_AUTHORIZE_URL + "?" + urlencode(
            {
                "client_id": self._api_key,
                "redirect_uri": self.redirect_uri(),
                "response_type": "code",
                "scope": scope,
                "state": self.new_login_state(),
            }
        )

    async def _post_form(self, url, data, headers=None):
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(url, data=data, headers=headers) as r:
                return json.loads(await r.text(encoding="utf-8"))
        except (aiohttp.ClientError, ValueError) as exception:
            _LOGGER.error("Kakao request to %s failed: %s", url, exception)
            return None

    def _token_payload(self, grant_type, **extra):
        payload = {"grant_type": grant_type, "client_id": self._api_key}
        if self._client_secret:
            payload["client_secret"] = self._client_secret
        payload.update(extra)
        return payload

    async def async_get_token(self, code):
        res = await self._post_form(
            OAUTH_TOKEN_URL,
            self._token_payload(
                "authorization_code", redirect_uri=self.redirect_uri(), code=code
            ),
        )
        if not res or "access_token" not in res:
            return res or {"error": "request_failed", "error_description": "Request failed"}

        self._access_token = res["access_token"]
        self._refresh_token = res.get("refresh_token", self._refresh_token)
        scope = res.get("scope", "")
        _LOGGER.info("Kakao login complete; granted scopes: %s", scope or "(none reported)")
        if self._send_to_friends and "friends" not in scope.split():
            _LOGGER.warning(
                "send_to_friends is on but Kakao did not grant the 'friends' scope. "
                "Check that the 'Friends list in Kakao services' consent item is set up "
                "in the Kakao console, then run the kakao_talk.login action again."
            )
        self._friends = []
        self._friends_fetched = 0.0
        await self.save_refresh_token()
        return res

    async def _async_refresh_access_token(self):
        """Refresh the access token. Returns True on success."""
        if not self._refresh_token:
            _LOGGER.error("Not logged in to KakaoTalk; run the kakao_talk.login action")
            return False
        res = await self._post_form(
            OAUTH_TOKEN_URL,
            self._token_payload("refresh_token", refresh_token=self._refresh_token),
        )
        if not res or "access_token" not in res:
            _LOGGER.error(
                "Kakao token refresh failed (run the kakao_talk.login action again): %s", res
            )
            return False
        self._access_token = res["access_token"]
        # Kakao only returns a new refresh token when the old one is close to expiry.
        if res.get("refresh_token"):
            self._refresh_token = res["refresh_token"]
            await self.save_refresh_token()
        return True

    # ------------------------------------------------------------------ API
    def _auth_headers(self):
        return {"Authorization": "Bearer " + self._access_token}

    async def _async_send(self, url, data, what):
        res = await self._post_form(url, data, self._auth_headers())
        if not res or res.get("result_code", 0) != 0 or "code" in res:
            _LOGGER.error("Kakao %s failed: %s", what, res)
        else:
            _LOGGER.debug("Kakao %s result: %s", what, res)
        return res

    async def _async_get_friends(self):
        friends = []
        offset = 0
        session = async_get_clientsession(self.hass)
        while True:
            try:
                async with session.get(
                    API_FRIENDS,
                    params={"offset": offset, "limit": FRIENDS_PAGE_SIZE},
                    headers=self._auth_headers(),
                ) as r:
                    res = json.loads(await r.text(encoding="utf-8"))
            except (aiohttp.ClientError, ValueError) as exception:
                _LOGGER.warning("KakaoTalk [Friends] request failed: %s", exception)
                return
            if "code" in res:
                _LOGGER.warning("KakaoTalk [Friends] Error : %s", res)
                return
            elements = res.get("elements", [])
            friends.extend(
                {"uuid": f["uuid"], "nickname": f.get("profile_nickname", "")}
                for f in elements
                if "uuid" in f
            )
            offset += len(elements)
            if not elements or offset >= res.get("total_count", 0):
                break
        self._friends = friends
        self._friends_fetched = time.monotonic()
        _LOGGER.debug("KakaoTalk [Friends] %d friends", len(friends))
        if not friends:
            _LOGGER.warning(
                "Kakao returned no friends. Until the app is reviewed, only Kakao Talk "
                "friends who are also app members and have consented to 'friends' and "
                "'talk_message' are returned (see the README)."
            )

    async def async_list_friends(self):
        """Fetch (fresh) and return the friends Kakao makes available to the app."""
        if not await self._async_refresh_access_token():
            return []
        await self._async_get_friends()
        return list(self._friends)

    def _recipient_uuids(self):
        if not self._friend_filter:
            return [f["uuid"] for f in self._friends]
        wanted = set(self._friend_filter)
        matched = [
            f
            for f in self._friends
            if f["uuid"].lower() in wanted or f["nickname"].strip().lower() in wanted
        ]
        found = {f["uuid"].lower() for f in matched} | {
            f["nickname"].strip().lower() for f in matched
        }
        missing = wanted - found
        if missing:
            _LOGGER.warning(
                "Configured friends not found in the friends Kakao returned: %s",
                sorted(missing),
            )
        return [f["uuid"] for f in matched]

    async def _async_send_to_friends(self, template):
        stale = time.monotonic() - self._friends_fetched > FRIENDS_CACHE_SECONDS
        if not self._friends or stale:
            await self._async_get_friends()
        uuids = self._recipient_uuids()
        if not uuids:
            _LOGGER.warning("send_to_friends is on but there are no recipients")
            return
        for i in range(0, len(uuids), FRIENDS_SEND_CHUNK):
            chunk = uuids[i : i + FRIENDS_SEND_CHUNK]
            res = await self._async_send(
                API_FRIENDS_SEND,
                {
                    "receiver_uuids": json.dumps(chunk),
                    "template_object": json.dumps(template, ensure_ascii=False),
                },
                "send to friends",
            )
            for failure in (res or {}).get("failure_info", []):
                _LOGGER.error(
                    "Kakao could not deliver to %s: %s (code %s)",
                    failure.get("receiver_uuids"),
                    failure.get("msg"),
                    failure.get("code"),
                )

    async def _async_send_template(self, template):
        if not await self._async_refresh_access_token():
            return

        await self._async_send(
            API_MEMO_SEND,
            {"template_object": json.dumps(template, ensure_ascii=False)},
            "send to me",
        )

        if self._send_to_friends:
            await self._async_send_to_friends(template)

    def _link(self):
        return {"web_url": self._link_url, "mobile_web_url": self._link_url}

    async def async_send_text(self, message):
        await self._async_send_template(
            {
                "object_type": "text",
                "text": message,
                "link": self._link(),
                "button_title": self._button_title,
            }
        )

    async def async_send_default_template(self, title, message, image_url):
        await self._async_send_template(
            {
                "object_type": "feed",
                "content": {
                    "title": title,
                    "description": message,
                    "image_url": image_url,
                    "link": self._link(),
                },
                "social": {},
                "button_title": self._button_title,
            }
        )


@callback
def async_register_http(hass, cfg):
    config = KakaoConfig(hass, cfg)
    hass.http.register_view(KakaoTalkView(config))

    async def send_message_handler(call: ServiceCall):
        """Handle the kakao_talk.send_message service."""
        title = call.data.get(ATTR_TITLE) or ""
        message = call.data.get("message", "")
        image_url = call.data.get(ATTR_URL)
        if image_url:
            await config.async_send_default_template(title, message, image_url)
            return
        await config.async_send_text(f"{title}\n\n{message}" if title else message)

    async def list_friends_handler(call: ServiceCall):
        """Return the friends (nickname + uuid) Kakao makes available to the app."""
        friends = await config.async_list_friends()
        return {"friends": friends}

    async def login_handler(call: ServiceCall):
        """Start a Kakao login. Only a Home Assistant admin may do this.

        Whoever completes a Kakao login becomes the account messages are sent as,
        so the login link (which carries a single-use state) is only ever given
        to an authenticated admin, never served from the unauthenticated page.
        """
        if call.context.user_id:
            user = await hass.auth.async_get_user(call.context.user_id)
            if user is None or not user.is_admin:
                raise Unauthorized(context=call.context)
        url = config.authorize_url()
        persistent_notification.async_create(
            hass,
            f"[Log in with KakaoTalk]({url})\n\n"
            "Open this link on a device on your home network. "
            "It can be used once and expires in 10 minutes.",
            title="KakaoTalk login",
            notification_id=LOGIN_NOTIFICATION_ID,
        )
        if call.return_response:
            return {"url": url}
        return None

    send_message_schema = vol.Schema(
        {
            vol.Required("message"): vol.All(cv.string, vol.Length(min=1)),
            vol.Optional(ATTR_TITLE): cv.string,
            vol.Optional(ATTR_URL): cv.string,
        }
    )

    hass.services.async_register(
        DOMAIN, SERVICE_SEND_MESSAGE, send_message_handler, schema=send_message_schema
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_FRIENDS,
        list_friends_handler,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LOGIN,
        login_handler,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.OPTIONAL,
    )


class KakaoTalkView(HomeAssistantView):
    """Setup page and OAuth callback.

    Authentication is disabled because Kakao redirects the browser here. The view
    cannot start a login and never sends messages: it only completes a login that
    an admin started with the kakao_talk.login action (checked via `state`).
    """

    url = KAKAO_TALK_API_ENDPOINT
    name = "api:kakao_talk"
    requires_auth = False

    def __init__(self, config):
        self.config = config

    async def _page(self):
        content = await self.config.get_setup_page()
        return web.Response(body=content, content_type="text/html", charset="utf-8")

    async def get(self, request):
        # Defence in depth: refuse anything that visibly comes from the internet.
        if not _is_local_request(self.config.hass, request):
            _LOGGER.warning(
                "Blocked non-local request to the KakaoTalk setup page from %s",
                request.remote,
            )
            return web.Response(status=403, text="Forbidden")

        query = request.rel_url.query

        if "image" in query:
            # Only serve files directly inside the images directory.
            path = IMAGES_DIR / os.path.basename(query["image"])
            if not path.is_file():
                return web.Response(status=404)
            return web.FileResponse(path)

        if "error" in query:
            _LOGGER.warning(
                "Kakao login error: %s %s",
                query.get("error"),
                query.get("error_description", ""),
            )
            return web.Response(
                text="{}: {}".format(
                    query.get("error"), query.get("error_description", "")
                ),
                status=200,
            )

        if "code" in query:
            if not self.config.consume_login_state(query.get("state")):
                _LOGGER.warning(
                    "Ignored Kakao login callback without a valid state. Start the "
                    "login with the kakao_talk.login action and finish within 10 minutes."
                )
                return web.Response(
                    text="This login was not started from Home Assistant, or it expired. "
                    "Run the kakao_talk.login action and try again.",
                    status=400,
                )
            res = await self.config.async_get_token(query["code"])
            if "access_token" not in res:
                error = res.get("error_description") or str(res)
                _LOGGER.warning("Kakao login failed: %s", error)
                return web.Response(text=error, status=200)
            persistent_notification.async_dismiss(
                self.config.hass, LOGIN_NOTIFICATION_ID
            )
            # Drop the one-time code and state from the address bar and history.
            raise web.HTTPFound(KAKAO_TALK_API_ENDPOINT + "?done=1")

        return await self._page()
