"""OAuth login, token handling and error paths."""
import json
from urllib.parse import parse_qs, urlparse

import pytest
import voluptuous as vol
from homeassistant.core import Context
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)

from custom_components.kakao_talk.const import DOMAIN

from .conftest import (
    CONFIG,
    FRIENDS_SEND_URL,
    FRIENDS_URL,
    MEMO_URL,
    TOKEN_URL,
    UPLOAD_URL,
    posts,
)


async def _login_url(hass):
    res = await hass.services.async_call(
        DOMAIN, "login", blocking=True, return_response=True
    )
    return res["url"]


async def test_login_returns_url_and_notification(hass, entry, monkeypatch):
    created = []
    monkeypatch.setattr(
        "custom_components.kakao_talk.http.persistent_notification.async_create",
        lambda h, msg, **kw: created.append((msg, kw)),
    )
    url = await _login_url(hass)
    assert url in created[0][0]
    assert created[0][1]["notification_id"] == "kakao_talk_login"
    q = parse_qs(urlparse(url).query)
    assert urlparse(url).netloc == "kauth.kakao.com"
    assert q["client_id"] == [CONFIG["api_key"]]
    assert q["redirect_uri"] == ["http://192.168.1.10:8123/api/kakao_talk"]
    assert q["scope"] == ["talk_message,friends"]  # send_to_friends is on in CONFIG
    assert len(q["state"][0]) >= 32


async def test_login_states_are_unique_and_bounded(hass, entry):
    states = {parse_qs(urlparse(await _login_url(hass)).query)["state"][0] for _ in range(8)}
    assert len(states) == 8
    assert len(hass.data[DOMAIN]["config"]._login_states) <= 5


async def test_login_denied_for_non_admin(hass, entry, hass_read_only_user):
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN, "login", blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )


async def test_login_allowed_for_admin(hass, entry, hass_admin_user):
    await hass.services.async_call(
        DOMAIN, "login", blocking=True, context=Context(user_id=hass_admin_user.id)
    )


async def test_callback_without_state_rejected(hass, entry, hass_client, kakao_api):
    client = await hass_client()
    resp = await client.get("/api/kakao_talk?code=abc", allow_redirects=False)
    assert resp.status == 400
    assert posts(kakao_api, TOKEN_URL) == []


async def test_callback_with_forged_state_rejected(hass, entry, hass_client, kakao_api):
    client = await hass_client()
    resp = await client.get("/api/kakao_talk?code=abc&state=forged", allow_redirects=False)
    assert resp.status == 400
    assert posts(kakao_api, TOKEN_URL) == []


async def test_callback_completes_login_once(hass, entry, hass_client, kakao_api):
    state = parse_qs(urlparse(await _login_url(hass)).query)["state"][0]
    client = await hass_client()
    resp = await client.get(f"/api/kakao_talk?code=thecode&state={state}", allow_redirects=False)
    assert resp.status == 302
    assert resp.headers["Location"].endswith("?done=1")
    [body] = posts(kakao_api, TOKEN_URL)
    assert body["grant_type"] == "authorization_code"
    assert body["code"] == "thecode"
    assert body["redirect_uri"] == "http://192.168.1.10:8123/api/kakao_talk"
    assert body["client_secret"] == "secret"
    # the new refresh token is stored on disk
    path = hass.config.path("kakao.session")
    assert (await hass.async_add_executor_job(lambda: open(path).read())) == "rt"
    # the state cannot be replayed
    resp = await client.get(f"/api/kakao_talk?code=thecode&state={state}", allow_redirects=False)
    assert resp.status == 400


async def test_callback_token_failure_reported(hass, entry, hass_client, aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json={"error": "invalid_grant", "error_description": "bad code"})
    state = parse_qs(urlparse(await _login_url(hass)).query)["state"][0]
    client = await hass_client()
    resp = await client.get(f"/api/kakao_talk?code=x&state={state}", allow_redirects=False)
    assert resp.status == 200
    assert "bad code" in await resp.text()


async def test_callback_error_param(hass, entry, hass_client):
    """Kakao's error text is shown for a login the administrator started."""
    state = parse_qs(urlparse(await _login_url(hass)).query)["state"][0]
    client = await hass_client()
    resp = await client.get(f"/api/kakao_talk?error=access_denied&error_description=nope&state={state}")
    assert resp.status == 200
    body = await resp.text()
    assert "access_denied" in body and "nope" in body
    # showing the error does not use the login up: the administrator can retry the link
    assert hass.data[DOMAIN]["config"].is_live_login_state(state)


async def test_unexpected_error_shows_no_text_from_the_request(hass, entry, hass_client, caplog):
    """A web page can send a browser at home here; its words must not appear on our page."""
    client = await hass_client()
    bait = "Session-expired-visit-evil.example"
    for query in (
        f"?error={bait}&error_description={bait}",
        f"?error={bait}&error_description={bait}&state=forged",
    ):
        resp = await client.get("/api/kakao_talk" + query)
        assert resp.status == 200
        body = await resp.text()
        assert bait not in body
        assert "Kakao reported a problem with the login" in body
    ours = [r for r in caplog.records if r.name.startswith("custom_components") and r.levelno >= 30]
    assert ours == []  # and it cannot be used to fill the warning log


async def test_setup_page_served(hass, entry, hass_client):
    client = await hass_client()
    resp = await client.get("/api/kakao_talk")
    assert resp.status == 200
    assert "text/html" in resp.headers["Content-Type"]


async def test_non_local_request_blocked(hass, entry, hass_client, monkeypatch):
    monkeypatch.setattr("custom_components.kakao_talk.http.is_cloud_connection", lambda h: True)
    client = await hass_client()
    resp = await client.get("/api/kakao_talk")
    assert resp.status == 403


async def test_view_503_when_not_set_up(hass, hass_client, entry):
    await hass.config_entries.async_unload(entry.entry_id)
    client = await hass_client()
    resp = await client.get("/api/kakao_talk")
    assert resp.status == 503


async def test_client_secret_omitted_when_empty(hass, entry, kakao_api):
    cfg = hass.data[DOMAIN]["config"]
    cfg._client_secret = ""
    await hass.services.async_call(DOMAIN, "send_message", {"message": "hi"}, blocking=True)
    [body, *_] = posts(kakao_api, TOKEN_URL)
    assert "client_secret" not in body


# ------------------------------------------------------------------ tokens
async def test_refresh_token_rotation_saved(hass, entry, aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json={"access_token": "at2", "refresh_token": "rt2"})
    aioclient_mock.post(MEMO_URL, json={"result_code": 0})
    await hass.services.async_call(DOMAIN, "send_message", {"message": "hi", "send_to_friends": False}, blocking=True)
    path = hass.config.path("kakao.session")
    assert (await hass.async_add_executor_job(lambda: open(path).read())) == "rt2"


async def test_failed_refresh_sends_nothing(hass, entry, aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json={"error": "invalid_grant"})
    aioclient_mock.post(MEMO_URL, json={"result_code": 0})
    with pytest.raises(HomeAssistantError, match="kakao_talk.login"):
        await hass.services.async_call(DOMAIN, "send_message", {"message": "hi"}, blocking=True)
    assert posts(aioclient_mock, MEMO_URL) == []
    assert posts(aioclient_mock, FRIENDS_SEND_URL) == []


async def test_not_logged_in_sends_nothing(hass, kakao_api):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    e = MockConfigEntry(domain=DOMAIN, data=dict(CONFIG), title="KakaoTalk")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(HomeAssistantError, match="kakao_talk.login"):
        await hass.services.async_call(DOMAIN, "send_message", {"message": "hi"}, blocking=True)
    assert posts(kakao_api, MEMO_URL) == []
    with pytest.raises(HomeAssistantError, match="kakao_talk.login"):
        await hass.services.async_call(DOMAIN, "list_friends", blocking=True, return_response=True)


async def test_session_file_is_private(hass, entry):
    import os
    import stat

    cfg = hass.data[DOMAIN]["config"]
    await cfg.save_refresh_token()
    mode = os.stat(hass.config.path("kakao.session")).st_mode
    if os.name == "posix":
        assert stat.S_IMODE(mode) == 0o600


# ------------------------------------------------------------------ send paths
async def test_empty_message_rejected(hass, entry):
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, "send_message", {"message": ""}, blocking=True)


async def test_friends_sent_in_chunks_of_five(hass, entry, aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json={"access_token": "at"})
    aioclient_mock.post(MEMO_URL, json={"result_code": 0})
    aioclient_mock.post(FRIENDS_SEND_URL, json={"successful_receiver_uuids": []})
    aioclient_mock.get(
        FRIENDS_URL,
        json={"total_count": 12, "elements": [{"uuid": f"u{i}", "profile_nickname": f"F{i}"} for i in range(12)]},
    )
    cfg = hass.data[DOMAIN]["config"]
    cfg._friends = []
    await hass.services.async_call(DOMAIN, "send_message", {"message": "hi"}, blocking=True)
    sent = posts(aioclient_mock, FRIENDS_SEND_URL)
    assert [len(json.loads(b["receiver_uuids"])) for b in sent] == [5, 5, 2]


async def test_friends_pagination(hass, entry, aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json={"access_token": "at"})
    aioclient_mock.get(
        FRIENDS_URL,
        json={"total_count": 3, "elements": [{"uuid": "a", "profile_nickname": "A"}]},
    )
    res = await hass.services.async_call(DOMAIN, "list_friends", blocking=True, return_response=True)
    # each page returns the same single element until total_count is reached
    assert len(res["friends"]) == 3


async def test_friends_api_error_does_not_crash(hass, entry, aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json={"access_token": "at"})
    aioclient_mock.post(MEMO_URL, json={"result_code": 0})
    aioclient_mock.get(FRIENDS_URL, json={"code": -402, "msg": "permission"})
    hass.data[DOMAIN]["config"]._friends = []
    await hass.services.async_call(DOMAIN, "send_message", {"message": "hi"}, blocking=True)
    assert len(posts(aioclient_mock, MEMO_URL)) == 1  # My Chatroom copy still sent


async def test_bad_input_is_a_validation_error(hass, entry):
    """User mistakes must surface as ServiceValidationError (HTTP 400), not a server error."""
    cases = [
        {"message": "m", "url": "https://x/a.jpg", "image": "media-source://x"},
        {"message": "m", "send_to_me": False, "send_to_friends": False},
        {"message": "m", "friends": ["Nobody"]},
    ]
    for data in cases:
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(DOMAIN, "send_message", data, blocking=True)


async def test_send_to_friends_requires_config(hass, kakao_api):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    await hass.async_add_executor_job(lambda: open(hass.config.path("kakao.session"), "w").write("rt"))
    e = MockConfigEntry(domain=DOMAIN, data={**CONFIG, "send_to_friends": False}, title="K")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "send_message", {"message": "hi", "send_to_friends": True}, blocking=True
        )


async def test_oversize_image_rejected(hass, entry, tmp_path, monkeypatch, kakao_api):
    img = tmp_path / "big.png"
    img.write_bytes(b"\0" * (5 * 1024 * 1024 + 1))

    class Item:
        path = img

    async def fake_resolve(*a):
        return Item()

    monkeypatch.setattr("homeassistant.components.media_source.async_resolve_media", fake_resolve)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "send_message", {"message": "m", "image": "media-source://x"}, blocking=True)
    assert posts(kakao_api, UPLOAD_URL) == []


async def test_upload_rejected_by_kakao(hass, entry, tmp_path, monkeypatch, aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json={"access_token": "at"})
    aioclient_mock.post(UPLOAD_URL, json={"code": -1, "msg": "bad"})
    img = tmp_path / "a.jpg"
    img.write_bytes(b"\xff\xd8\xff")

    class Item:
        path = img

    async def fake_resolve(*a):
        return Item()

    monkeypatch.setattr("homeassistant.components.media_source.async_resolve_media", fake_resolve)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "send_message", {"message": "m", "image": "media-source://x"}, blocking=True)


async def test_network_error_does_not_crash(hass, entry, aioclient_mock):
    import aiohttp

    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, exc=aiohttp.ClientError("boom"))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "send_message", {"message": "hi"}, blocking=True)


async def test_reload_preserves_services(hass, entry):
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    for svc in ("send_message", "list_friends", "login"):
        assert hass.services.has_service(DOMAIN, svc)


# ------------------------------------------------------------------ hardening
async def test_error_page_is_themed_and_sanitised(hass, entry, hass_client, caplog):
    state = parse_qs(urlparse(await _login_url(hass)).query)["state"][0]
    client = await hass_client()
    resp = await client.get(
        "/api/kakao_talk",
        params={"error": "denied", "error_description": "a" * 500, "state": state},
    )
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("text/html")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    body = await resp.text()
    assert "a" * 200 in body and "a" * 201 not in body  # the description is capped


async def test_forbidden_and_bad_state_have_nosniff(hass, entry, hass_client, monkeypatch):
    client = await hass_client()
    resp = await client.get("/api/kakao_talk?code=a&state=b")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    monkeypatch.setattr("custom_components.kakao_talk.http.is_cloud_connection", lambda h: True)
    resp = await client.get("/api/kakao_talk")
    assert resp.status == 403
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


async def test_non_object_json_from_kakao_is_handled(hass, entry, aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json=["not", "an", "object"])
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "send_message", {"message": "hi"}, blocking=True)


async def test_non_object_friends_response_is_handled(hass, entry, aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json={"access_token": "at"})
    aioclient_mock.get(FRIENDS_URL, json=["nope"])
    res = await hass.services.async_call(DOMAIN, "list_friends", blocking=True, return_response=True)
    assert res["friends"] == []


async def test_secrets_not_logged(hass, entry, caplog, hass_client, kakao_api):
    caplog.set_level("DEBUG")
    state = parse_qs(urlparse(await _login_url(hass)).query)["state"][0]
    client = await hass_client()
    await client.get(f"/api/kakao_talk?code=thecode&state={state}", allow_redirects=False)
    await hass.services.async_call(DOMAIN, "send_message", {"message": "hi"}, blocking=True)
    ours = "\n".join(
        r.getMessage() for r in caplog.records if r.name.startswith("custom_components")
    )
    assert ours  # the integration did log something
    for secret in ("thecode", "secret", "rest-key", "client_secret", '"at"', '"rt"'):
        assert secret not in ours


def test_clean_for_log_strips_control_characters_and_caps_length():
    from custom_components.kakao_talk.http import _clean_for_log

    assert _clean_for_log("a\r\nFAKE LOG LINE\x00b") == "a  FAKE LOG LINE b"
    assert _clean_for_log(None) == ""
    assert len(_clean_for_log("x" * 1000)) == 200


# ------------------------------------------------------------------ clear image errors
def _resolve_to(monkeypatch, item):
    async def fake_resolve(*args):
        return item

    monkeypatch.setattr("homeassistant.components.media_source.async_resolve_media", fake_resolve)


async def test_non_local_image_error_is_clear(hass, entry, monkeypatch):
    class Item:  # e.g. a camera or add-on source: a URL but no file path
        path = None
        url = "/api/frigate/snapshot.jpg"

    _resolve_to(monkeypatch, Item())
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "send_message",
            {"message": "m", "image": {"media_content_id": "media-source://frigate/event/1"}},
            blocking=True,
        )
    text = str(err.value)
    assert "'frigate' media source" in text
    assert "My media" in text
    assert "Image URL" in text


async def test_unopenable_image_error_has_hint(hass, entry, monkeypatch):
    async def boom(*args):
        raise ValueError("nope")

    monkeypatch.setattr("homeassistant.components.media_source.async_resolve_media", boom)
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN, "send_message", {"message": "m", "image": "/some/url.jpg"}, blocking=True
        )
    text = str(err.value)
    assert "/some/url.jpg" in text and "nope" in text
    assert "My media" in text


def test_media_source_name():
    from custom_components.kakao_talk.http import _media_source_name

    assert _media_source_name("media-source://camera/abc") == "the 'camera' media source"
    assert _media_source_name("/api/image.jpg") == "a source other than Local media"
    assert _media_source_name(None) == "a source other than Local media"
