import json
import logging
import os
from pathlib import Path
from urllib.parse import urlencode

import aiohttp
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.notify import ATTR_TITLE
from homeassistant.core import ServiceCall, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    ATTR_URL,
    CONF_API_KEY,
    CONF_BUTTON_TITLE,
    CONF_CLIENT_SECRET,
    CONF_REDIRECT_URI,
    CONF_SEND_TO_FRIENDS,
    DOMAIN,
    KAKAO_TALK_API_ENDPOINT,
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

DEFAULT_BUTTON_TITLE = "View"


def _read_text(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as file:
        return file.read()


def _read_session(path):
    if not os.path.exists(path) or os.stat(path).st_size == 0:
        return None
    return _read_text(path).strip() or None


def _write_text(path, content):
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)


class KakaoConfig:
    def __init__(self, hass, config):
        self.hass = hass
        self._api_key = config.get(CONF_API_KEY)
        self._client_secret = config.get(CONF_CLIENT_SECRET)
        self._button_title = config.get(CONF_BUTTON_TITLE) or DEFAULT_BUTTON_TITLE
        self._host = config.get(CONF_REDIRECT_URI)
        self._send_to_friends = config.get(CONF_SEND_TO_FRIENDS)
        self._friends = []
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
            _LOGGER.warning("Please login on Kakaotalk!! (open /api/kakao_talk)")

    async def save_refresh_token(self):
        path = self.hass.config.path(SESSION_FILE)
        try:
            await self.hass.async_add_executor_job(
                _write_text, path, self._refresh_token
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
    def redirect_uri(self, request):
        """The OAuth redirect URI; must match the one registered at Kakao."""
        base = (self._host or "").rstrip("/")
        if not base.startswith(("http://", "https://")):
            base = "{}://{}".format(request.scheme, request.host)
        return base + KAKAO_TALK_API_ENDPOINT

    def authorize_url(self, request):
        scope = "talk_message"
        if self._send_to_friends:
            scope += ",friends"
        return OAUTH_AUTHORIZE_URL + "?" + urlencode(
            {
                "client_id": self._api_key,
                "redirect_uri": self.redirect_uri(request),
                "response_type": "code",
                "scope": scope,
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

    async def async_get_token(self, code, redirect_uri):
        res = await self._post_form(
            OAUTH_TOKEN_URL,
            self._token_payload(
                "authorization_code", redirect_uri=redirect_uri, code=code
            ),
        )
        if not res or "access_token" not in res:
            return res or {"error": "request_failed", "error_description": "Request failed"}

        self._access_token = res["access_token"]
        self._refresh_token = res.get("refresh_token", self._refresh_token)
        self._friends = []
        await self.save_refresh_token()
        return res

    async def _async_refresh_access_token(self):
        """Refresh the access token. Returns True on success."""
        if not self._refresh_token:
            _LOGGER.error("Not logged in to KakaoTalk; open /api/kakao_talk to login")
            return False
        res = await self._post_form(
            OAUTH_TOKEN_URL,
            self._token_payload("refresh_token", refresh_token=self._refresh_token),
        )
        if not res or "access_token" not in res:
            _LOGGER.error(
                "Kakao token refresh failed (login again at /api/kakao_talk): %s", res
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
                break
            if "code" in res:
                _LOGGER.warning("KakaoTalk [Friends] Error : %s", res)
                break
            elements = res.get("elements", [])
            friends.extend(f["uuid"] for f in elements if "uuid" in f)
            offset += len(elements)
            if not elements or offset >= res.get("total_count", 0):
                break
        self._friends = friends
        _LOGGER.debug("KakaoTalk [Friends] %d friends", len(friends))

    async def _async_send_template(self, template):
        if not await self._async_refresh_access_token():
            return

        await self._async_send(
            API_MEMO_SEND,
            {"template_object": json.dumps(template, ensure_ascii=False)},
            "send to me",
        )

        if self._send_to_friends:
            if not self._friends:
                await self._async_get_friends()
            for i in range(0, len(self._friends), FRIENDS_SEND_CHUNK):
                chunk = self._friends[i : i + FRIENDS_SEND_CHUNK]
                await self._async_send(
                    API_FRIENDS_SEND,
                    {
                        "receiver_uuids": json.dumps(chunk),
                        "template_object": json.dumps(template, ensure_ascii=False),
                    },
                    "send to friends",
                )

    def _link(self):
        return {"web_url": self._host, "mobile_web_url": self._host}

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

    hass.services.async_register(DOMAIN, SERVICE_SEND_MESSAGE, send_message_handler)


class KakaoTalkView(HomeAssistantView):
    """Login/setup page and OAuth callback.

    Authentication is disabled because Kakao redirects the browser here.
    The view never sends messages; it only handles login.
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
        query = request.rel_url.query

        if "image" in query:
            # Only serve files directly inside the images directory.
            path = IMAGES_DIR / os.path.basename(query["image"])
            if not path.is_file():
                return web.Response(status=404)
            return web.FileResponse(path)

        if "login" in query:
            raise web.HTTPFound(self.config.authorize_url(request))

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
            res = await self.config.async_get_token(
                query["code"], self.config.redirect_uri(request)
            )
            if "access_token" not in res:
                error = res.get("error_description") or str(res)
                _LOGGER.warning("Kakao login failed: %s", error)
                return web.Response(text=error, status=200)

        return await self._page()
