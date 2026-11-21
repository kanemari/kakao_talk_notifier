"""Linking a friend: Kakao links a friend to the app only when their one-time code is exchanged."""
from urllib.parse import parse_qs, urlparse

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized

from custom_components.kakao_talk.const import DOMAIN
from custom_components.kakao_talk.http import (
    INVITE_FAILED,
    LINK_ATTEMPTS,
    _extract_code,
    _mask,
)

from .conftest import TOKEN_URL, posts
from .test_invite import CODE, INVITE_STATE, from_internet, public_entry  # noqa: F401  (fixtures)
from .test_landing import HOSTED, hosted_entry

LOCAL_REDIRECT = "http://192.168.1.10:8123/api/kakao_talk"


def exchanges(mock):
    return [b for b in posts(mock, TOKEN_URL) if b.get("grant_type") == "authorization_code"]


def capture_notifications(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "custom_components.kakao_talk.http.persistent_notification.async_create",
        lambda h, msg, **kw: seen.__setitem__(kw.get("notification_id"), msg),
    )
    return seen


async def link(hass, code=CODE, **kwargs):
    return await hass.services.async_call(
        DOMAIN, "link_friend", {"code": code}, blocking=True, return_response=True, **kwargs
    )


# ------------------------------------------------------------------ reading a code
def test_extract_code_accepts_a_code_or_an_address_that_contains_one():
    assert _extract_code(CODE) == CODE
    assert _extract_code(f"  {CODE}\n") == CODE
    assert _extract_code(f"http://192.168.1.10:8123/api/kakao_talk?code={CODE}&state={INVITE_STATE}") == CODE
    assert _extract_code(f"code={CODE}&state=x") == CODE
    assert _extract_code(f"?code={CODE}") == CODE


@pytest.mark.parametrize(
    "text",
    ["", None, "short", "a" * 9, "has space " + "a" * 20, "<script>alert(1)</script>" + "a" * 20,
     "a" * 600, "code=", "code=short", "../../etc/passwd" * 3, "a" * 20 + "\n" + "b" * 20, "a" * 20 + "%00"],
)
def test_extract_code_rejects_anything_that_is_not_a_code(text):
    assert _extract_code(text) is None


def test_mask_removes_the_code_from_text():
    assert _mask(f"not found for code={CODE}", CODE) == "not found for code=[code]"
    assert _mask("nothing here", CODE) == "nothing here"


# ------------------------------------------------------------------ the callback (friend returns to HA)
async def test_the_friend_is_linked_and_nothing_is_kept(hass, entry, hass_client, aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.post(
        TOKEN_URL,
        json={"access_token": "FRIEND-AT", "refresh_token": "FRIEND-RT", "scope": "talk_message friends"},
    )
    cfg = hass.data[DOMAIN]["config"]
    before = (cfg._access_token, cfg._refresh_token, dict(cfg._login_states))
    session = hass.config.path("kakao.session")
    session_before = await hass.async_add_executor_job(lambda: open(session).read())
    client = await hass_client()
    resp = await client.get(f"/api/kakao_talk?code={CODE}&state={INVITE_STATE}")
    assert resp.status == 200 and "Your permission was recorded" in await resp.text()
    assert len(exchanges(aioclient_mock)) == 1
    # the friend's token is never kept: not in memory, not on disk, not in a header we send later
    assert (cfg._access_token, cfg._refresh_token, dict(cfg._login_states)) == before
    assert await hass.async_add_executor_job(lambda: open(session).read()) == session_before
    for value in vars(cfg).values():
        assert "FRIEND-AT" not in repr(value) and "FRIEND-RT" not in repr(value)


async def test_a_refused_code_gives_a_fixed_failure_page(hass, entry, hass_client, aioclient_mock, caplog):
    aioclient_mock.clear_requests()
    aioclient_mock.post(
        TOKEN_URL,
        json={"error": "invalid_grant", "error_description": f"authorization code not found for code={CODE}"},
    )
    client = await hass_client()
    resp = await client.get(f"/api/kakao_talk?code={CODE}&state={INVITE_STATE}")
    body = await resp.text()
    assert resp.status == 200
    assert "Could not link you" in body and INVITE_FAILED in body
    assert "Your permission was recorded" not in body
    assert CODE not in body and "invalid_grant" not in body and "authorization code" not in body
    # and Kakao's words, which repeat the code, are not logged by the integration either
    ours = [r.getMessage() for r in caplog.records if r.name.startswith("custom_components")]
    assert not any(CODE in message for message in ours)


async def test_a_value_that_is_not_a_code_never_reaches_kakao(hass, entry, hass_client, aioclient_mock):
    client = await hass_client()
    for value, ours in (
        ("short", True),
        ("has%20space%20in%20it%20and%20is%20long", True),
        ("%3Cscript%3Ealert(1)%3C/script%3Eaaaaaaaaa", False),  # Home Assistant's own filter answers first
    ):
        resp = await client.get(f"/api/kakao_talk?code={value}&state={INVITE_STATE}")
        assert resp.status == 400
        if ours:
            assert "Could not link you" in await resp.text()
    assert exchanges(aioclient_mock) == []


async def test_a_flood_of_codes_is_limited(hass, entry, hass_client, aioclient_mock):
    client = await hass_client()
    statuses = [
        (await client.get(f"/api/kakao_talk?code={CODE}{i}&state={INVITE_STATE}")).status
        for i in range(LINK_ATTEMPTS + 3)
    ]
    assert statuses == [200] * LINK_ATTEMPTS + [429] * 3
    assert len(exchanges(aioclient_mock)) == LINK_ATTEMPTS  # Kakao is not sent the rest


async def test_the_limit_applies_to_the_internet_too(hass, public_entry, hass_client, aioclient_mock, from_internet):
    client = await hass_client()
    for i in range(LINK_ATTEMPTS):
        assert (await client.get(f"/api/kakao_talk?code={CODE}{i}&state={INVITE_STATE}")).status == 200
    resp = await client.get(f"/api/kakao_talk?code={CODE}z&state={INVITE_STATE}")
    assert resp.status == 429 and await resp.text() == "Too many requests. Please try again in a minute."


async def test_linking_announces_it_and_what_the_friend_agreed_to(hass, entry, hass_client, aioclient_mock, monkeypatch):
    seen = capture_notifications(monkeypatch)
    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json={"access_token": "at", "scope": "talk_message friends"})
    client = await hass_client()
    await client.get(f"/api/kakao_talk?code={CODE}&state={INVITE_STATE}")
    text = seen["kakao_talk_friend_linked"]
    assert "Permissions they agreed to: talk_message, friends." in text
    assert "10 minutes" in text and "did NOT agree" not in text


async def test_it_warns_when_the_friend_did_not_agree_to_the_friends_list(hass, entry, hass_client, aioclient_mock, monkeypatch):
    seen = capture_notifications(monkeypatch)
    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json={"access_token": "at", "scope": "talk_message"})
    client = await hass_client()
    await client.get(f"/api/kakao_talk?code={CODE}&state={INVITE_STATE}")
    assert "did NOT agree to the friends list" in seen["kakao_talk_friend_linked"]


async def test_no_notification_when_linking_fails(hass, entry, hass_client, aioclient_mock, monkeypatch):
    seen = capture_notifications(monkeypatch)
    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json={"error": "invalid_grant"})
    client = await hass_client()
    await client.get(f"/api/kakao_talk?code={CODE}&state={INVITE_STATE}")
    assert "kakao_talk_friend_linked" not in seen


async def test_the_exchange_uses_the_redirect_in_the_invite_link(hass, kakao_api, hass_client):
    await hosted_entry(hass)
    client = await hass_client()  # at home, a friend can still return here: the redirect must match the link
    await client.get(f"/api/kakao_talk?code={CODE}&state={INVITE_STATE}")
    [body] = exchanges(kakao_api)
    assert body["redirect_uri"] == HOSTED


# ------------------------------------------------------------------ the action (relay path)
async def test_the_action_links_a_friend_from_the_code(hass, entry, kakao_api):
    res = await link(hass)
    assert res["linked"] is True and res["permissions"] == []
    assert "10 minutes" in res["note"]
    [body] = exchanges(kakao_api)
    assert body["code"] == CODE and body["redirect_uri"] == LOCAL_REDIRECT
    assert body["client_id"] == "rest-key" and body["client_secret"] == "secret"


async def test_the_action_uses_the_hosted_page_as_the_redirect(hass, kakao_api):
    await hosted_entry(hass)
    await link(hass)
    assert exchanges(kakao_api)[0]["redirect_uri"] == HOSTED


async def test_the_action_uses_a_bare_public_address_as_the_redirect(hass, kakao_api):
    await hosted_entry(hass, invite_redirect_uri="https://ha.example.com")
    await link(hass)
    assert exchanges(kakao_api)[0]["redirect_uri"] == "https://ha.example.com/api/kakao_talk"


async def test_the_action_accepts_the_whole_address(hass, entry, kakao_api):
    await link(hass, f"http://192.168.1.10:8123/api/kakao_talk?code={CODE}&state={INVITE_STATE}")
    assert exchanges(kakao_api)[0]["code"] == CODE


async def test_the_action_refuses_what_is_not_a_code(hass, entry, kakao_api):
    for text in ("short", "not a code at all, sorry", "<b>" + "a" * 30):
        with pytest.raises(ServiceValidationError, match="does not look like a code"):
            await link(hass, text)
    assert exchanges(kakao_api) == []


async def test_the_action_explains_a_refusal_without_repeating_the_code(hass, entry, aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.post(
        TOKEN_URL,
        json={"error": "invalid_grant", "error_description": f"authorization code not found for code={CODE}"},
    )
    with pytest.raises(HomeAssistantError) as err:
        await link(hass)
    text = str(err.value)
    assert "Kakao refused the code" in text and "authorization code not found" in text
    assert CODE not in text and "[code]" in text
    assert "new link" in text


async def test_the_action_keeps_no_token(hass, entry, aioclient_mock):
    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json={"access_token": "FRIEND-AT", "refresh_token": "FRIEND-RT"})
    cfg = hass.data[DOMAIN]["config"]
    before = (cfg._access_token, cfg._refresh_token)
    session = hass.config.path("kakao.session")
    session_before = await hass.async_add_executor_job(lambda: open(session).read())
    res = await link(hass)
    assert "FRIEND-AT" not in repr(res) and "FRIEND-RT" not in repr(res)
    assert (cfg._access_token, cfg._refresh_token) == before
    assert await hass.async_add_executor_job(lambda: open(session).read()) == session_before


async def test_the_action_is_for_administrators_only(hass, entry, kakao_api, hass_read_only_user, hass_admin_user):
    with pytest.raises(Unauthorized):
        await link(hass, context=Context(user_id=hass_read_only_user.id))
    assert exchanges(kakao_api) == []
    assert (await link(hass, context=Context(user_id=hass_admin_user.id)))["linked"] is True


async def test_the_action_announces_the_link(hass, entry, kakao_api, monkeypatch):
    seen = capture_notifications(monkeypatch)
    await link(hass)
    assert "kakao_talk_friend_linked" in seen


async def test_the_action_is_registered_and_unloaded(hass, entry):
    assert hass.services.has_service(DOMAIN, "link_friend")
    await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service(DOMAIN, "link_friend")


def test_the_action_is_described():
    from pathlib import Path

    from homeassistant.util.yaml import load_yaml

    import custom_components.kakao_talk as component

    services = load_yaml(str(Path(component.__file__).parent / "services.yaml"))
    field = services["link_friend"]["fields"]["code"]
    assert field["required"] is True and "text" in field["selector"]


# ------------------------------------------------------------------ the whole relay path
async def test_the_invite_link_and_the_action_use_the_same_redirect(hass, kakao_api):
    await hosted_entry(hass)
    invite = await hass.services.async_call(DOMAIN, "friend_invite_link", blocking=True, return_response=True)
    sent = parse_qs(urlparse(invite["url"]).query)["redirect_uri"][0]
    await link(hass)
    assert exchanges(kakao_api)[0]["redirect_uri"] == sent == HOSTED
