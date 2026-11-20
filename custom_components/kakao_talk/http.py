import json
import logging
import mimetypes
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
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID
from homeassistant.core import ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import is_cloud_connection
from homeassistant.util.network import is_local

from . import pages
from .const import (
    ATTR_FRIENDS,
    ATTR_IMAGE,
    ATTR_LINK_TO_IMAGE,
    ATTR_LINK_URL,
    ATTR_SEND_TO_FRIENDS,
    ATTR_SEND_TO_ME,
    ATTR_URL,
    CONF_API_KEY,
    CONF_BUTTON_TITLE,
    CONF_CLIENT_SECRET,
    CONF_FRIEND_ENTITIES,
    CONF_FRIENDS,
    CONF_INVITE_REDIRECT_URI,
    CONF_LINK_TO_IMAGE,
    CONF_LINK_URL,
    CONF_REDIRECT_URI,
    CONF_SEND_TO_FRIENDS,
    DOMAIN,
    FRIEND_UNIQUE_PREFIX,
    KAKAO_TALK_API_ENDPOINT,
    SERVICE_LIST_FRIENDS,
    SERVICE_FRIEND_INVITE_LINK,
    SERVICE_LOGIN,
    SERVICE_SEND_MESSAGE,
    SESSION_FILE,
)

_LOGGER = logging.getLogger(__name__)

COMPONENT_DIR = Path(__file__).parent
SETUP_PAGE = COMPONENT_DIR / "setup.html"

OAUTH_AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
OAUTH_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
API_MEMO_SEND = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
API_IMAGE_UPLOAD = "https://kapi.kakao.com/v2/api/talk/message/image/upload"
API_FRIENDS = "https://kapi.kakao.com/v1/api/talk/friends"
API_FRIENDS_SEND = "https://kapi.kakao.com/v1/api/talk/friends/message/default/send"

FRIENDS_PAGE_SIZE = 100
# Kakao limits the number of receivers per friends-message request.
FRIENDS_SEND_CHUNK = 5
# How long the friends list is cached before it is fetched again.
FRIENDS_CACHE_SECONDS = 3600

# Kakao accepts JPEG and PNG images up to 5 MB for upload.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = ("image/jpeg", "image/png")

DEFAULT_BUTTON_TITLE = "View"

# How long a started login stays valid, in seconds.
LOGIN_STATE_SECONDS = 600
# Only this many started logins are remembered at once.
MAX_LOGIN_STATES = 5
LOGIN_NOTIFICATION_ID = "kakao_talk_login"
INVITE_NOTIFICATION_ID = "kakao_talk_friend_invite"
# Fixed marker for friend invite links. The callback never exchanges the code of an
# invite, so it cannot start, replace or complete a login (see KakaoTalkView.get).
INVITE_STATE = "kakao_talk_invite"
INVITE_THANKS = "Your permission was recorded. You can close this page."
# Fixed text: nothing from the request is ever shown on a page the internet can reach.
INVITE_DECLINED = (
    "Permissions were not accepted. If you want to try again, ask the person who "
    "invited you for the link and open it once more."
)
LOGIN_DONE_NOTIFICATION_ID = "kakao_talk_login_done"

# Kakao calls must not hang a Home Assistant action or the login callback.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# A blocked request from the internet is logged as a warning at most this often,
# so that a stranger cannot fill the log.
BLOCKED_LOG_SECONDS = 600
_blocked_logged_at = float("-inf")


def _log_blocked(remote):
    global _blocked_logged_at
    now = time.monotonic()
    if now - _blocked_logged_at >= BLOCKED_LOG_SECONDS:
        _blocked_logged_at = now
        _LOGGER.warning(
            "Blocked a request to the KakaoTalk page that did not come from the local "
            "network (from %s). Further blocked requests are logged at debug level "
            "for the next 10 minutes.",
            remote,
        )
    else:
        _LOGGER.debug("Blocked non-local request to the KakaoTalk page from %s", remote)

_FRIENDS_HINT = (
    "If it mentions a missing permission, turn on Also send to friends in the settings, "
    "run kakao_talk.login and agree to the friends permission. The Home Assistant log has "
    "Kakao's full reply."
)
_NO_FRIENDS_NOTE = (
    "Kakao returned no friends. Each friend must be invited under App > Member in the "
    "Kakao Developers console, have signed in there, and have agreed to the friends "
    "permission (send them the kakao_talk.friend_invite_link link). You must be logged "
    "in with the friends permission: turn on Also send to friends, then run kakao_talk.login."
)

_LOGIN_REQUIRED = (
    "Could not sign in to KakaoTalk. Run the kakao_talk.login action to log in "
    "again; the Home Assistant log has the details."
)


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


_LOCAL_IMAGE_HINT = (
    "Only image files stored in Home Assistant's Local media (Media > My media) "
    "can be uploaded: copy the image there and pick it again, or use the Image "
    "URL field with a public address instead."
)


def _media_source_name(media_id):
    """Human-readable source of a media-source:// id, for error messages."""
    text = str(media_id or "")
    if text.startswith("media-source://"):
        name = text[len("media-source://"):].split("/", 1)[0]
        if name:
            return "the '" + name + "' media source"
    return "a source other than Local media"


def _clean_for_log(value, limit=200):
    """Make untrusted text safe to log or show: single line, no control characters."""
    text = "".join(c if c.isprintable() else " " for c in str(value or ""))
    return text[:limit]


def _plain(text, status=200):
    """A plain-text response that browsers must not reinterpret as HTML."""
    return web.Response(
        text=text, status=status, headers={"X-Content-Type-Options": "nosniff"}
    )


def _themed(title, message, ok=True, status=200):
    """A small page with the project icon and colours (see pages.py).

    The text is escaped and the page carries a strict Content-Security-Policy. Pass
    only fixed text, or text that went through _clean_for_log.
    """
    return web.Response(
        text=pages.render(title, message, ok),
        status=status,
        content_type="text/html",
        charset="utf-8",
        headers={
            "Content-Security-Policy": pages.CSP,
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


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
        # Optional public address friends are sent back to after agreeing, so it works
        # away from home. Only the thank-you page of a friend invite is served there.
        self._invite_host = config.get(CONF_INVITE_REDIRECT_URI)
        # Open the image itself (not Home Assistant) when an image message is tapped.
        self._link_to_image = bool(config.get(CONF_LINK_TO_IMAGE))
        self._login_states = {}
        self._send_to_friends = config.get(CONF_SEND_TO_FRIENDS)
        # Show each friend as a notify entity (on unless the owner turned it off).
        self._friend_entities = bool(config.get(CONF_FRIEND_ENTITIES, True))
        # Optional filter: nicknames or uuids to send to. Empty means everyone returned.
        self._friend_filter = [str(f).strip().lower() for f in config.get(CONF_FRIENDS) or []]
        self._friends = []  # list of {"uuid": ..., "nickname": ...}
        self._friends_fetched = 0.0
        # Why the last fetch of the friends list failed, or None if it worked.
        self._friends_error = None
        self._access_token = None
        self._refresh_token = None

        # Called with the friends list each time it is fetched (see notify.py).
        self._friend_listeners = []

        _LOGGER.debug("KakaoConfig %s", self._host)
        self._session_task = hass.async_create_task(self._load_session())

    # ------------------------------------------------------------------ session
    async def _load_session(self):
        path = self.hass.config.path(SESSION_FILE)
        token = await self.hass.async_add_executor_job(_read_session, path)
        if token:
            self._refresh_token = token
        else:
            _LOGGER.warning("Not logged in to KakaoTalk yet; run the kakao_talk.login action")

    def add_friends_listener(self, listener):
        """Call listener(friends) every time the friends list is fetched. Returns a remover."""
        self._friend_listeners.append(listener)

        def remove():
            if listener in self._friend_listeners:
                self._friend_listeners.remove(listener)

        return remove

    def _notify_friends_changed(self):
        for listener in list(self._friend_listeners):
            try:
                listener(list(self._friends))
            except Exception:  # a broken listener must not break sending
                _LOGGER.exception("A friends listener failed")

    async def async_refresh_friends(self):
        """Fetch the friends list in the background. Never raises."""
        if not self._send_to_friends:
            return
        try:
            await self._session_task
            if self._refresh_token and await self._async_refresh_access_token():
                await self._async_get_friends()
        except Exception as exception:
            _LOGGER.debug("Refreshing the friends list failed: %s", exception)

    async def _async_friends_after_login(self):
        """After a login, fetch the friends with the token we just received."""
        try:
            await self._async_get_friends()
        except Exception as exception:
            _LOGGER.debug("Fetching the friends after login failed: %s", exception)

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

    def is_live_login_state(self, state):
        """True if `state` belongs to a login an administrator started (not used up)."""
        return self._login_states.get(state or "", 0) > time.monotonic()

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

    @property
    def invite_is_public(self):
        """True if friends may come back from an invite over the internet."""
        return bool(self._invite_host)

    @property
    def has_client_secret(self):
        return bool(self._client_secret)

    def invite_redirect_uri(self):
        """Where Kakao sends a friend back after they agree.

        The public address for invites if one is set, otherwise the normal address.
        It must be registered as a Redirect URI at Kakao.
        """
        return (self._invite_host or self._host).rstrip("/") + KAKAO_TALK_API_ENDPOINT

    def invite_url(self):
        """Kakao consent link to give to a friend, so Kakao records their permission.

        The friend signs in and agrees to the friends and message permissions. The
        link carries a fixed marker as `state`; when Kakao sends the friend back, the
        callback shows a thank-you page and ignores the code. It cannot log anyone in
        to this integration, so it is safe to share with the people you invited.
        """
        return OAUTH_AUTHORIZE_URL + "?" + urlencode(
            {
                "client_id": self._api_key,
                "redirect_uri": self.invite_redirect_uri(),
                "response_type": "code",
                "scope": "talk_message,friends",
                "state": INVITE_STATE,
            }
        )

    async def _post_form(self, url, data, headers=None):
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                url, data=data, headers=headers, timeout=REQUEST_TIMEOUT
            ) as r:
                res = json.loads(await r.text(encoding="utf-8"))
        except (aiohttp.ClientError, TimeoutError, ValueError) as exception:
            _LOGGER.error("Kakao request to %s failed: %s", url, exception)
            return None
        if not isinstance(res, dict):
            _LOGGER.error("Kakao request to %s returned an unexpected response", url)
            return None
        return res

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
        if self._send_to_friends:
            # Show the friends in the Actions form soon after logging in.
            self.hass.async_create_task(self._async_friends_after_login())
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

    @staticmethod
    def _send_failed(res):
        return not res or res.get("result_code", 0) != 0 or "code" in res

    @staticmethod
    def _describe_template(template):
        """One line for the debug log: what kind of message and where a tap leads."""
        link = (template.get("content") or template).get("link") or {}
        return "type={} link={} button={!r}".format(
            template.get("object_type"), link.get("web_url"), template.get("button_title")
        )

    async def _async_send_template_object(self, url, extra, template, fallback, what):
        """POST a template. If Kakao refuses it and a fallback is given, retry once with that."""
        _LOGGER.debug("Kakao %s: %s", what, self._describe_template(template))
        res = await self._async_send(
            url,
            {**extra, "template_object": json.dumps(template, ensure_ascii=False)},
            what,
        )
        if fallback is not None and self._send_failed(res):
            _LOGGER.warning(
                "Kakao refused the message with the image as its link (usually the "
                "image's domain is not registered under Product Link > Web domain). "
                "Sending it again with the normal link."
            )
            _LOGGER.debug("Kakao %s (retry): %s", what, self._describe_template(fallback))
            res = await self._async_send(
                url,
                {**extra, "template_object": json.dumps(fallback, ensure_ascii=False)},
                what,
            )
        return res

    async def _async_get_friends(self):
        """Fetch the friends list. True if it worked; False (and _friends_error says why) if not.

        A failed fetch leaves the friends we already know unchanged.
        """
        friends = []
        offset = 0
        session = async_get_clientsession(self.hass)
        while True:
            try:
                async with session.get(
                    API_FRIENDS,
                    params={"offset": offset, "limit": FRIENDS_PAGE_SIZE},
                    headers=self._auth_headers(),
                    timeout=REQUEST_TIMEOUT,
                ) as r:
                    res = json.loads(await r.text(encoding="utf-8"))
            except (aiohttp.ClientError, TimeoutError, ValueError) as exception:
                _LOGGER.warning("KakaoTalk [Friends] request failed: %s", exception)
                self._friends_error = f"the request failed ({exception})"
                return False
            if not isinstance(res, dict):
                _LOGGER.warning("KakaoTalk [Friends] returned an unexpected response")
                self._friends_error = "Kakao sent an unexpected reply"
                return False
            if "code" in res:
                _LOGGER.warning("KakaoTalk [Friends] Error : %s", res)
                self._friends_error = "Kakao error {}: {}".format(
                    res.get("code"), _clean_for_log(res.get("msg"), 120)
                )
                return False
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
        self._friends_error = None
        _LOGGER.debug("KakaoTalk [Friends] %d friends", len(friends))
        self._notify_friends_changed()
        if not friends:
            _LOGGER.warning(
                "Kakao returned no friends. Until the app is reviewed, only Kakao Talk "
                "friends who are also app members and have consented to 'friends' and "
                "'talk_message' are returned (see the README)."
            )
        return True

    @property
    def friend_entities_enabled(self):
        """True if friends should be offered as entities (needs friends to be on)."""
        return bool(self._send_to_friends) and self._friend_entities

    @property
    def send_to_friends(self):
        return bool(self._send_to_friends)

    async def async_list_friends(self):
        """Fetch (fresh) and return the friends Kakao makes available to the app."""
        if not await self._async_refresh_access_token():
            raise HomeAssistantError(_LOGIN_REQUIRED)
        if not await self._async_get_friends():
            # Say why, rather than returning an empty list that looks like "no friends".
            raise HomeAssistantError(
                f"Kakao could not return the friends list: {self._friends_error}. "
                + _FRIENDS_HINT
            )
        return list(self._friends)

    def _recipient_uuids(self, requested=None):
        """Return (uuids, unmatched) for the requested names/uuids, or the configured filter."""
        wanted_list = (
            [str(f).strip().lower() for f in requested]
            if requested is not None
            else self._friend_filter
        )
        if not wanted_list:
            return [f["uuid"] for f in self._friends], []
        wanted = set(wanted_list)
        matched = [
            f
            for f in self._friends
            if f["uuid"].lower() in wanted or f["nickname"].strip().lower() in wanted
        ]
        found = {f["uuid"].lower() for f in matched} | {
            f["nickname"].strip().lower() for f in matched
        }
        missing = sorted(wanted - found)
        if missing:
            _LOGGER.warning(
                "Friends not found in the friends Kakao returned: %s", ", ".join(missing)
            )
        return [f["uuid"] for f in matched], missing

    async def _async_send_to_friends(self, template, requested=None, fallback=None):
        stale = time.monotonic() - self._friends_fetched > FRIENDS_CACHE_SECONDS
        if not self._friends or stale:
            await self._async_get_friends()
        uuids, missing = self._recipient_uuids(requested)
        if not uuids:
            if requested is not None:
                raise ServiceValidationError(
                    "None of the requested friends were found: "
                    + ", ".join(requested)
                    + ". Run kakao_talk.list_friends to see who Kakao returns."
                )
            _LOGGER.warning("send_to_friends is on but there are no recipients")
            return
        for i in range(0, len(uuids), FRIENDS_SEND_CHUNK):
            chunk = uuids[i : i + FRIENDS_SEND_CHUNK]
            res = await self._async_send_template_object(
                API_FRIENDS_SEND,
                {"receiver_uuids": json.dumps(chunk)},
                template,
                fallback,
                "send to friends",
            )
            for failure in (res or {}).get("failure_info", []):
                _LOGGER.error(
                    "Kakao could not deliver to %s: %s (code %s)",
                    failure.get("receiver_uuids"),
                    failure.get("msg"),
                    failure.get("code"),
                )

    async def _async_send_template(
        self, template, friends=None, send_to_friends=None, send_to_me=True, fallback=None
    ):
        """Send a template.

        friends: names/uuids for this message only (overrides the configured list).
        send_to_friends: per-message override of the configured setting.
        send_to_me: also send a copy to My Chatroom.
        fallback: a template to retry with once if Kakao refuses `template`.
        """
        if send_to_friends is None:
            send_to_friends = True if friends else self._send_to_friends
        if send_to_friends and not self._send_to_friends:
            raise ServiceValidationError(
                "Sending to friends needs 'Also send to friends' turned on in the "
                "KakaoTalk Notifier settings, then a new kakao_talk.login."
            )
        if not send_to_me and not send_to_friends:
            raise ServiceValidationError(
                "Nothing to do: both send_to_me and send_to_friends are off."
            )
        if not await self._async_refresh_access_token():
            raise HomeAssistantError(_LOGIN_REQUIRED)

        if send_to_me:
            await self._async_send_template_object(
                API_MEMO_SEND, {}, template, fallback, "send to me"
            )

        if send_to_friends:
            await self._async_send_to_friends(template, friends or None, fallback)

    async def async_upload_image(self, media):
        """Upload a Home Assistant media item to Kakao and return its public URL."""
        from homeassistant.components import media_source

        media_id = media.get("media_content_id") if isinstance(media, dict) else media
        if not media_id:
            raise ServiceValidationError("No image selected.")
        try:
            item = await media_source.async_resolve_media(self.hass, media_id, None)
        except Exception as exception:  # media_source raises several types
            raise HomeAssistantError(
                f"Could not open the selected image ({media_id}): {exception}. "
                + _LOCAL_IMAGE_HINT
            ) from exception
        path = getattr(item, "path", None)
        if path is None:
            raise ServiceValidationError(
                f"The selected image comes from {_media_source_name(media_id)}, which "
                "cannot be uploaded to Kakao. " + _LOCAL_IMAGE_HINT
            )
        content_type = mimetypes.guess_type(path.name)[0]
        if content_type not in IMAGE_TYPES:
            raise ServiceValidationError("Kakao only accepts JPEG and PNG images.")
        # Check the size on disk first, so a huge file is never read into memory.
        try:
            size = await self.hass.async_add_executor_job(lambda: path.stat().st_size)
        except OSError as exception:
            raise HomeAssistantError(
                f"Could not read the selected image: {exception}"
            ) from exception
        if size > MAX_IMAGE_BYTES:
            raise ServiceValidationError("Kakao only accepts images up to 5 MB.")
        data = await self.hass.async_add_executor_job(path.read_bytes)
        if len(data) > MAX_IMAGE_BYTES:
            raise ServiceValidationError("Kakao only accepts images up to 5 MB.")
        if not await self._async_refresh_access_token():
            raise HomeAssistantError(_LOGIN_REQUIRED)
        form = aiohttp.FormData()
        form.add_field("file", data, filename=path.name, content_type=content_type)
        res = await self._post_form(API_IMAGE_UPLOAD, form, self._auth_headers())
        url = (((res or {}).get("infos") or {}).get("original") or {}).get("url")
        if not url:
            _LOGGER.error("Kakao image upload failed: %s", res)
            raise HomeAssistantError("Kakao rejected the image upload, see the log.")
        _LOGGER.debug("Kakao image uploaded: %s", url)
        return url

    def _link(self, url=None):
        url = url or self._link_url
        return {"web_url": url, "mobile_web_url": url}

    async def async_send_text(self, message, link_url=None, **kwargs):
        await self._async_send_template(
            {
                "object_type": "text",
                "text": message,
                "link": self._link(link_url),
                "button_title": self._button_title,
            },
            **kwargs,
        )

    async def async_send_default_template(
        self, title, message, image_url, link_url=None, link_to_image=None, **kwargs
    ):
        """Send an image card.

        Tapping it opens link_url if given, else the image itself when link_to_image
        (or the setting) is on, else the configured link address.
        """
        if link_to_image is None:
            link_to_image = self._link_to_image

        def template(link):
            return {
                "object_type": "feed",
                "content": {
                    "title": title,
                    "description": message,
                    "image_url": image_url,
                    "link": self._link(link),
                },
                "social": {},
                "button_title": self._button_title,
            }

        if link_url:
            primary, fallback = template(link_url), None
        elif link_to_image:
            # The image's domain may not be registered at Kakao; retry once if refused.
            primary, fallback = template(image_url), template(None)
        else:
            primary, fallback = template(None), None
        await self._async_send_template(primary, fallback=fallback, **kwargs)


@callback
def async_setup_view(hass):
    """Register the setup page / OAuth callback once. It finds the active entry itself."""
    hass.http.register_view(KakaoTalkView(hass))


@callback
def async_unregister_services(hass):
    for service in (
        SERVICE_SEND_MESSAGE,
        SERVICE_LIST_FRIENDS,
        SERVICE_LOGIN,
        SERVICE_FRIEND_INVITE_LINK,
    ):
        hass.services.async_remove(DOMAIN, service)


def _friend_uuids_from_target(hass, call):
    """The Kakao uuids of the friend entities picked as the target of a call.

    Uses only the entity and device registries (not Home Assistant's target helpers,
    whose location and signature change between versions). Explicitly picked
    entities must be KakaoTalk friends. A device means all the friends on it.
    """
    for key in ("area_id", "floor_id", "label_id"):
        if call.data.get(key):
            raise ServiceValidationError(
                "Pick friends, or the KakaoTalk device, under Targets. Areas, floors "
                "and labels are not supported."
            )
    registry = er.async_get(hass)

    def friend_uuid(entry):
        unique_id = (entry.unique_id or "") if entry else ""
        if entry and entry.platform == DOMAIN and unique_id.startswith(FRIEND_UNIQUE_PREFIX):
            return unique_id[len(FRIEND_UNIQUE_PREFIX):]
        return None

    uuids = []

    def add(uuid):
        if uuid and uuid not in uuids:
            uuids.append(uuid)

    entity_ids = call.data.get(ATTR_ENTITY_ID)
    if entity_ids == "all":
        for entry in list(registry.entities.values()):
            add(friend_uuid(entry))
    elif entity_ids and entity_ids != "none":
        for entity_id in cv.ensure_list(entity_ids):
            uuid = friend_uuid(registry.async_get(entity_id))
            if uuid is None:
                raise ServiceValidationError(
                    f"{entity_id} is not a KakaoTalk friend. Pick friends from the "
                    "KakaoTalk list, or use the friends field."
                )
            add(uuid)

    for device_id in cv.ensure_list(call.data.get(ATTR_DEVICE_ID) or []):
        for entry in er.async_entries_for_device(registry, device_id):
            add(friend_uuid(entry))  # anything on the device that is not a friend is ignored
    return uuids


@callback
def async_register_services(hass, config):
    async def send_message_handler(call: ServiceCall):
        """Handle the kakao_talk.send_message service."""
        title = call.data.get(ATTR_TITLE) or ""
        message = call.data.get("message", "")
        image_url = call.data.get(ATTR_URL)
        if image_url and call.data.get(ATTR_IMAGE):
            raise ServiceValidationError("Use either url or image, not both.")
        if call.data.get(ATTR_IMAGE):
            image_url = await config.async_upload_image(call.data[ATTR_IMAGE])
        friends = call.data.get(ATTR_FRIENDS)
        picked = _friend_uuids_from_target(hass, call)
        if picked:
            # Friends picked in the form (entities) are added to any names typed in.
            friends = list(dict.fromkeys([*(friends or []), *picked]))
        options = {
            "friends": friends,
            "send_to_friends": call.data.get(ATTR_SEND_TO_FRIENDS),
            "send_to_me": call.data.get(ATTR_SEND_TO_ME, True),
        }
        link_url = call.data.get(ATTR_LINK_URL)
        if image_url:
            await config.async_send_default_template(
                title,
                message,
                image_url,
                link_url=link_url,
                link_to_image=call.data.get(ATTR_LINK_TO_IMAGE),
                **options,
            )
            return
        await config.async_send_text(
            f"{title}\n\n{message}" if title else message, link_url=link_url, **options
        )

    async def list_friends_handler(call: ServiceCall):
        """Return the friends (nickname + uuid) Kakao makes available to the app."""
        friends = await config.async_list_friends()
        if not friends:
            return {"friends": [], "note": _NO_FRIENDS_NOTE}
        return {"friends": friends}

    async def _require_admin(call: ServiceCall):
        """Only an authenticated Home Assistant administrator may continue."""
        if call.context.user_id:
            user = await hass.auth.async_get_user(call.context.user_id)
            if user is None or not user.is_admin:
                raise Unauthorized(context=call.context)

    async def friend_invite_link_handler(call: ServiceCall):
        """Give the administrator a link a friend opens to give their permission.

        A friend who should receive messages has to agree once to the friends and
        message permissions. This link asks for exactly that, instead of the friend
        having to use the Kakao console. It cannot log anyone in to this integration.
        """
        await _require_admin(call)
        if not config.has_client_secret:
            # A friend's one-time code ends up in the address of the page they are sent
            # back to. Without a client secret, anyone who saw that address could use
            # the code; with one, the code is useless to them.
            raise ServiceValidationError(
                "Friend invites need a Client secret. Turn on Client secret for the "
                "REST API key in the Kakao Developers console, enter it in the "
                "KakaoTalk Notifier settings, then run kakao_talk.login again."
            )
        url = config.invite_url()
        persistent_notification.async_create(
            hass,
            f"[Friend invite link]({url})\n\n"
            "Send this link to a friend you have invited under App > Member in the "
            "Kakao Developers console. They open it, sign in to Kakao and agree. "
            "It can be used by any number of friends and does not expire. It cannot "
            "log anyone in to Home Assistant or replace your own Kakao login.",
            title="KakaoTalk friend invite",
            notification_id=INVITE_NOTIFICATION_ID,
        )
        if call.return_response:
            return {"url": url}
        return None

    async def login_handler(call: ServiceCall):
        """Start a Kakao login. Only a Home Assistant admin may do this.

        Whoever completes a Kakao login becomes the account messages are sent as,
        so the login link (which carries a single-use state) is only ever given
        to an authenticated admin, never served from the unauthenticated page.
        """
        await _require_admin(call)
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
            vol.Optional(ATTR_IMAGE): vol.Any(cv.string, dict),
            vol.Optional(ATTR_LINK_URL): cv.string,
            vol.Optional(ATTR_LINK_TO_IMAGE): cv.boolean,
            vol.Optional(ATTR_FRIENDS): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional(ATTR_SEND_TO_FRIENDS): cv.boolean,
            vol.Optional(ATTR_SEND_TO_ME): cv.boolean,
            **cv.TARGET_SERVICE_FIELDS,
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
    hass.services.async_register(
        DOMAIN,
        SERVICE_FRIEND_INVITE_LINK,
        friend_invite_link_handler,
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

    def __init__(self, hass):
        self._hass = hass

    @property
    def config(self):
        """The KakaoConfig of the loaded config entry, or None."""
        return self._hass.data.get(DOMAIN, {}).get("config")

    async def _page(self):
        content = await self.config.get_setup_page()
        # Browsers hash inline blocks after normalising line ends, so serve "\n" only.
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        return web.Response(
            text=content,
            content_type="text/html",
            charset="utf-8",
            headers={
                "Content-Security-Policy": pages.csp_for(content),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    async def get(self, request):
        config = self.config
        query = request.rel_url.query
        # A friend coming back from a friend invite. The answer is a fixed text: it
        # changes nothing, stores nothing and shows nothing from the request.
        is_invite = query.get("state") == INVITE_STATE and (
            "code" in query or "error" in query
        )
        # Only that answer may be reached from the internet, and only if the owner
        # set a public address for friend invites. Everything else must be local.
        allow_remote = is_invite and config is not None and config.invite_is_public
        if not allow_remote and not _is_local_request(self._hass, request):
            _log_blocked(request.remote)
            return _plain("Forbidden", 403)

        if config is None:
            return _plain("KakaoTalk is not set up.", 503)

        if is_invite:
            # The code is deliberately never exchanged: no token is requested, nothing
            # is stored and no login happens.
            if "error" in query:
                _LOGGER.debug(
                    "A friend invite was declined or failed: %s",
                    _clean_for_log(query.get("error"), 60),
                )
                return _themed("Permissions not accepted", INVITE_DECLINED, ok=False)
            _LOGGER.debug("A friend followed the invite link and gave their permission")
            return _themed("Thank you", INVITE_THANKS)

        if "error" in query:
            error = _clean_for_log(query.get("error"))
            description = _clean_for_log(query.get("error_description"))
            if not self.config.is_live_login_state(query.get("state")):
                # Not a login we started: a web page could send a browser on the home
                # network here with words of its own, so never put them on our page.
                _LOGGER.debug("Ignored an unexpected login error: %s %s", error, description)
                return _themed(
                    "Kakao login error",
                    "Kakao reported a problem with the login. Run the kakao_talk.login "
                    "action and try again.",
                    ok=False,
                )
            _LOGGER.warning("Kakao login error: %s %s", error, description)
            return _themed("Kakao login error", f"{error}: {description}", ok=False)

        if "code" in query:
            if not self.config.consume_login_state(query.get("state")):
                _LOGGER.warning(
                    "Ignored Kakao login callback without a valid state. Start the "
                    "login with the kakao_talk.login action and finish within 10 minutes."
                )
                return _themed(
                    "Login not started",
                    "This login was not started from Home Assistant, or it expired. "
                    "Run the kakao_talk.login action and try again.",
                    ok=False,
                    status=400,
                )
            res = await self.config.async_get_token(query["code"])
            if "access_token" not in res:
                error = _clean_for_log(res.get("error_description") or res)
                _LOGGER.warning("Kakao login failed: %s", error)
                return _themed("Login failed", error, ok=False)
            persistent_notification.async_dismiss(
                self.config.hass, LOGIN_NOTIFICATION_ID
            )
            # Make every completed login visible, so an unexpected one is noticed.
            persistent_notification.async_create(
                self.config.hass,
                "A KakaoTalk login was just completed. Messages are now sent as the "
                "Kakao account that logged in.\n\nIf this was not you, run the "
                "kakao_talk.login action again to log in with your own account, and "
                "check who can sign in to Home Assistant.",
                title="KakaoTalk login completed",
                notification_id=LOGIN_DONE_NOTIFICATION_ID,
            )
            # Drop the one-time code and state from the address bar and history.
            raise web.HTTPFound(KAKAO_TALK_API_ENDPOINT + "?done=1")

        return await self._page()
