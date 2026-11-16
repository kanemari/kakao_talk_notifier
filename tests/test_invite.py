"""The friend invite link: a friend gives their permission without being able to log in."""
from urllib.parse import parse_qs, urlparse

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import Unauthorized

from custom_components.kakao_talk.const import DOMAIN

from .conftest import CONFIG, TOKEN_URL, posts

INVITE_STATE = "kakao_talk_invite"


async def invite(hass, **kwargs):
    res = await hass.services.async_call(
        DOMAIN, "friend_invite_link", blocking=True, return_response=True, **kwargs
    )
    return res["url"]


async def test_service_is_registered_and_unloaded(hass, entry):
    assert hass.services.has_service(DOMAIN, "friend_invite_link")
    await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service(DOMAIN, "friend_invite_link")


async def test_link_asks_for_the_friend_permissions(hass, entry):
    url = await invite(hass)
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://kauth.kakao.com/oauth/authorize"
    assert q["client_id"] == [CONFIG["api_key"]]
    assert q["redirect_uri"] == ["http://192.168.1.10:8123/api/kakao_talk"]
    assert q["response_type"] == ["code"]
    assert set(q["scope"][0].split(",")) == {"talk_message", "friends"}
    assert q["state"] == [INVITE_STATE]


async def test_link_asks_for_friends_even_if_sending_to_friends_is_off(hass, kakao_api):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    e = MockConfigEntry(domain=DOMAIN, data={**CONFIG, "send_to_friends": False}, title="K")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    q = parse_qs(urlparse(await invite(hass)).query)
    assert "friends" in q["scope"][0].split(",")


async def test_link_is_the_same_each_time_and_not_a_login(hass, entry):
    cfg = hass.data[DOMAIN]["config"]
    assert await invite(hass) == await invite(hass)
    assert cfg._login_states == {}  # creating invites never creates a login state


async def test_notification_is_created(hass, entry, monkeypatch):
    created = []
    monkeypatch.setattr(
        "custom_components.kakao_talk.http.persistent_notification.async_create",
        lambda h, msg, **kw: created.append((msg, kw)),
    )
    url = await invite(hass)
    assert url in created[0][0]
    assert created[0][1]["notification_id"] == "kakao_talk_friend_invite"


async def test_admin_only(hass, entry, hass_read_only_user, hass_admin_user):
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN, "friend_invite_link", blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    await hass.services.async_call(
        DOMAIN, "friend_invite_link", blocking=True,
        context=Context(user_id=hass_admin_user.id),
    )


# ------------------------------------------------------------------ callback
async def test_callback_thanks_the_friend_and_ignores_the_code(hass, entry, hass_client, kakao_api):
    client = await hass_client()
    resp = await client.get(f"/api/kakao_talk?code=friendcode&state={INVITE_STATE}", allow_redirects=False)
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("text/plain")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "permission" in await resp.text()
    assert posts(kakao_api, TOKEN_URL) == []  # the code is never exchanged


async def test_friend_cannot_replace_the_login(hass, entry, hass_client, kakao_api):
    """Using the invite marker must never store a token or change who messages are sent as."""
    cfg = hass.data[DOMAIN]["config"]
    before = (cfg._access_token, cfg._refresh_token)
    client = await hass_client()
    for _ in range(3):  # can be used any number of times
        resp = await client.get(f"/api/kakao_talk?code=friendcode&state={INVITE_STATE}", allow_redirects=False)
        assert resp.status == 200
    assert (cfg._access_token, cfg._refresh_token) == before
    assert posts(kakao_api, TOKEN_URL) == []
    path = hass.config.path("kakao.session")
    assert (await hass.async_add_executor_job(lambda: open(path).read())) == "rt"


async def test_invite_marker_needs_a_code(hass, entry, hass_client, kakao_api):
    client = await hass_client()
    resp = await client.get(f"/api/kakao_talk?state={INVITE_STATE}")
    assert resp.status == 200  # the plain setup page, not the thank-you message
    assert "permission was recorded" not in await resp.text()


async def test_forged_state_is_still_rejected(hass, entry, hass_client, kakao_api):
    client = await hass_client()
    for state in ("forged", "kakao_talk_invite2", "KAKAO_TALK_INVITE"):
        resp = await client.get(f"/api/kakao_talk?code=x&state={state}", allow_redirects=False)
        assert resp.status == 400
    assert posts(kakao_api, TOKEN_URL) == []


async def test_real_login_still_works(hass, entry, hass_client, kakao_api):
    res = await hass.services.async_call(DOMAIN, "login", blocking=True, return_response=True)
    state = parse_qs(urlparse(res["url"]).query)["state"][0]
    assert state != INVITE_STATE
    client = await hass_client()
    resp = await client.get(f"/api/kakao_talk?code=thecode&state={state}", allow_redirects=False)
    assert resp.status == 302
    assert len(posts(kakao_api, TOKEN_URL)) == 1


@pytest.fixture
def from_internet(monkeypatch):
    """Make every request look like it came from the internet (e.g. Nabu Casa)."""
    monkeypatch.setattr("custom_components.kakao_talk.http.is_cloud_connection", lambda h: True)


async def test_internet_may_reach_only_the_invite_thank_you(hass, entry, hass_client, kakao_api, from_internet):
    client = await hass_client()
    resp = await client.get(f"/api/kakao_talk?code=friendcode&state={INVITE_STATE}", allow_redirects=False)
    assert resp.status == 200
    assert "permission was recorded" in await resp.text()
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert posts(kakao_api, TOKEN_URL) == []


async def test_internet_may_see_a_declined_invite(hass, entry, hass_client, from_internet):
    client = await hass_client()
    resp = await client.get(f"/api/kakao_talk?error=access_denied&state={INVITE_STATE}")
    assert resp.status == 200
    assert "access_denied" in await resp.text()


async def test_internet_still_refused_for_everything_else(hass, entry, hass_client, kakao_api, from_internet):
    client = await hass_client()
    for query in (
        "",  # the setup page
        "?state=" + INVITE_STATE,  # the marker alone is not enough
        "?code=x&state=forged",
        "?code=x",
        "?error=access_denied",
        "?error=access_denied&state=forged",
        "?done=1",
    ):
        resp = await client.get("/api/kakao_talk" + query, allow_redirects=False)
        assert resp.status == 403, query
    assert posts(kakao_api, TOKEN_URL) == []


async def test_internet_cannot_complete_a_real_login(hass, entry, hass_client, kakao_api, monkeypatch):
    """Even a valid single-use login state is refused when the request is not local."""
    res = await hass.services.async_call(DOMAIN, "login", blocking=True, return_response=True)
    state = parse_qs(urlparse(res["url"]).query)["state"][0]
    monkeypatch.setattr("custom_components.kakao_talk.http.is_cloud_connection", lambda h: True)
    client = await hass_client()
    resp = await client.get(f"/api/kakao_talk?code=thecode&state={state}", allow_redirects=False)
    assert resp.status == 403
    assert posts(kakao_api, TOKEN_URL) == []
    # the state was not used up, so the administrator can still finish the login at home
    monkeypatch.setattr("custom_components.kakao_talk.http.is_cloud_connection", lambda h: False)
    resp = await client.get(f"/api/kakao_talk?code=thecode&state={state}", allow_redirects=False)
    assert resp.status == 302


async def test_invite_visits_are_not_logged_as_warnings(hass, entry, hass_client, from_internet, caplog):
    client = await hass_client()
    await client.get(f"/api/kakao_talk?code=c&state={INVITE_STATE}")
    await client.get(f"/api/kakao_talk?error=access_denied&state={INVITE_STATE}")
    ours = [r for r in caplog.records if r.name.startswith("custom_components") and r.levelno >= 30]
    assert ours == []


# ------------------------------------------------------------------ public address setting
async def _entry_with(hass, **extra):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    e = MockConfigEntry(domain=DOMAIN, data={**CONFIG, **extra}, title="K")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    return e


async def test_invite_uses_the_public_address_when_set(hass, kakao_api):
    await _entry_with(hass, invite_redirect_uri="https://ha.example.com")
    q = parse_qs(urlparse(await invite(hass)).query)
    assert q["redirect_uri"] == ["https://ha.example.com/api/kakao_talk"]


async def test_login_link_keeps_the_local_address(hass, kakao_api):
    await _entry_with(hass, invite_redirect_uri="https://ha.example.com")
    res = await hass.services.async_call(DOMAIN, "login", blocking=True, return_response=True)
    assert parse_qs(urlparse(res["url"]).query)["redirect_uri"] == ["http://192.168.1.10:8123/api/kakao_talk"]


async def test_invite_defaults_to_the_normal_address(hass, entry):
    q = parse_qs(urlparse(await invite(hass)).query)
    assert q["redirect_uri"] == ["http://192.168.1.10:8123/api/kakao_talk"]


async def test_public_address_is_saved_validated_and_trimmed(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    bad = await hass.config_entries.options.async_configure(
        result["flow_id"], {**CONFIG, "invite_redirect_uri": "not a url"}
    )
    assert bad["errors"] == {"invite_redirect_uri": "invalid_url"}
    ok = await hass.config_entries.options.async_configure(
        result["flow_id"], {**CONFIG, "invite_redirect_uri": " https://ha.example.com/ "}
    )
    await hass.async_block_till_done()
    assert entry.data["invite_redirect_uri"] == "https://ha.example.com"


async def test_public_address_left_empty_is_not_stored(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], {**CONFIG, "invite_redirect_uri": ""})
    await hass.async_block_till_done()
    assert "invite_redirect_uri" not in entry.data


async def test_decline_shows_kakaos_message(hass, entry, hass_client):
    client = await hass_client()
    resp = await client.get(
        f"/api/kakao_talk?error=access_denied&error_description=user+cancelled&state={INVITE_STATE}"
    )
    assert resp.status == 200
    assert "access_denied" in await resp.text()
