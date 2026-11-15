import json
from urllib.parse import parse_qs, urlparse
from homeassistant.setup import async_setup_component

CFG = {"kakao_talk": {"api_key": "KEY", "client_secret": "SEC",
       "redirect_uri": "https://ha.example.com:8123", "send_to_friends": True, "button_title": "Open"},
       "notify": [{"platform": "kakao_talk", "name": "kakao_talk"}]}

async def test_flow(hass, hass_client_no_auth, aioclient_mock):
    aioclient_mock.post("https://kauth.kakao.com/oauth/token", json={"access_token": "AT", "refresh_token": "RT1"})
    aioclient_mock.post("https://kapi.kakao.com/v2/api/talk/memo/default/send", json={"result_code": 0})
    aioclient_mock.get("https://kapi.kakao.com/v1/api/talk/friends", json={"elements": [{"uuid": f"u{i}"} for i in range(7)], "total_count": 7})
    aioclient_mock.post("https://kapi.kakao.com/v1/api/talk/friends/message/default/send", json={"result_code": 0})
    assert await async_setup_component(hass, "kakao_talk", CFG)
    assert await async_setup_component(hass, "notify", CFG)
    await hass.async_block_till_done()
    assert hass.services.has_service("kakao_talk", "send_message")
    assert hass.services.has_service("notify", "kakao_talk")

    client = await hass_client_no_auth()
    r = await client.get("/api/kakao_talk", allow_redirects=False)
    assert r.status == 200 and "KEY" not in await r.text()
    r = await client.get("/api/kakao_talk?login=1", allow_redirects=False)
    assert r.status == 302
    q = parse_qs(urlparse(r.headers["Location"]).query)
    assert q["scope"] == ["talk_message,friends"]
    assert q["redirect_uri"] == ["https://ha.example.com:8123/api/kakao_talk"]
    assert (await client.get("/api/kakao_talk?image=../../manifest.json")).status in (400, 404)
    assert (await client.get("/api/kakao_talk?image=kakaotalk-hassio.png")).status == 200
    assert (await client.get("/api/kakao_talk?message=hi")).status == 200  # just the page now

    r = await client.get("/api/kakao_talk?code=CODE&state=" + q["state"][0])
    assert r.status == 200
    tok = [c for c in aioclient_mock.mock_calls if "oauth/token" in str(c[1])][0]

    aioclient_mock.clear_requests()
    aioclient_mock.post("https://kauth.kakao.com/oauth/token", json={"access_token": "AT2", "refresh_token": "RT2"})
    aioclient_mock.post("https://kapi.kakao.com/v2/api/talk/memo/default/send", json={"result_code": 0})
    aioclient_mock.get("https://kapi.kakao.com/v1/api/talk/friends", json={"elements": [{"uuid": f"u{i}"} for i in range(7)], "total_count": 7})
    aioclient_mock.post("https://kapi.kakao.com/v1/api/talk/friends/message/default/send", json={"result_code": 0})
    await hass.services.async_call("notify", "kakao_talk", {"title": "T", "message": "a&b%c+d"}, blocking=True)
    sends = [c for c in aioclient_mock.mock_calls if "send" in str(c[1])]
    assert len(sends) == 3  # me + 2 friend chunks (5+2)
    assert json.loads(sends[0][2]["template_object"])["button_title"] == "Open"
    assert json.loads(sends[0][2]["template_object"])["text"] == "T\n\na&b%c+d"
    assert open(hass.config.path("kakao.session")).read() == "RT2"

    await hass.services.async_call("notify", "kakao_talk", {"message": "m", "data": {"photo": [{"url": "http://x/y.png"}]}}, blocking=True)
    assert json.loads([c for c in aioclient_mock.mock_calls if "memo" in str(c[1])][-1][2]["template_object"])["object_type"] == "feed"


FRIENDS = [{"uuid": "uA", "profile_nickname": "Alice"}, {"uuid": "uB", "profile_nickname": "Bob"},
           {"uuid": "uC", "profile_nickname": "Carol"}]


async def test_friend_filter_and_failures(hass, aioclient_mock, caplog):
    cfg = {"kakao_talk": {**CFG["kakao_talk"], "friends": ["alice", "uC", "Nobody"]}}
    aioclient_mock.post("https://kauth.kakao.com/oauth/token", json={"access_token": "AT"})
    aioclient_mock.post("https://kapi.kakao.com/v2/api/talk/memo/default/send", json={"result_code": 0})
    aioclient_mock.get("https://kapi.kakao.com/v1/api/talk/friends", json={"elements": FRIENDS, "total_count": 3})
    aioclient_mock.post(
        "https://kapi.kakao.com/v1/api/talk/friends/message/default/send",
        json={"successful_receiver_uuids": ["uA"],
              "failure_info": [{"code": -532, "msg": "daily message limit per sender has been exceeded.",
                                "receiver_uuids": ["uC"]}]},
    )
    assert await async_setup_component(hass, "kakao_talk", cfg)
    await hass.async_block_till_done()
    # pretend a login happened so a refresh token exists
    with open(hass.config.path("kakao.session"), "w") as f:
        f.write("RT")
    await hass.services.async_call("kakao_talk", "send_message", {"message": "hi"}, blocking=True)

    sends = [c for c in aioclient_mock.mock_calls if "friends/message" in str(c[1])]
    assert len(sends) == 1
    assert json.loads(sends[0][2]["receiver_uuids"]) == ["uA", "uC"]
    assert "daily message limit" in caplog.text
    assert "Nobody" in caplog.text.lower() or "nobody" in caplog.text.lower()

    res = await hass.services.async_call("kakao_talk", "list_friends", {}, blocking=True, return_response=True)
    assert res == {"friends": [{"uuid": "uA", "nickname": "Alice"}, {"uuid": "uB", "nickname": "Bob"},
                               {"uuid": "uC", "nickname": "Carol"}]}


async def test_login_page_is_not_reachable_from_internet_or_forgeable(hass, hass_client_no_auth, aioclient_mock):
    from unittest.mock import patch

    aioclient_mock.post("https://kauth.kakao.com/oauth/token", json={"access_token": "ATTACKER", "refresh_token": "RT-ATTACKER"})
    assert await async_setup_component(hass, "kakao_talk", CFG)
    await hass.async_block_till_done()
    client = await hass_client_no_auth()

    # From a non-local address everything is refused, including starting a login.
    with patch("custom_components.kakao_talk.http._is_local_request", return_value=False):
        for path in ("/api/kakao_talk", "/api/kakao_talk?login=1", "/api/kakao_talk?code=X&state=Y",
                     "/api/kakao_talk?image=kakaotalk-hassio.png"):
            assert (await client.get(path, allow_redirects=False)).status == 403

    # Even locally, a callback with a missing/forged state does not store a token.
    for path in ("/api/kakao_talk?code=X", "/api/kakao_talk?code=X&state=forged"):
        assert (await client.get(path)).status == 400
    assert not [c for c in aioclient_mock.mock_calls if "oauth/token" in str(c[1])]

    # A state can only be used once.
    r = await client.get("/api/kakao_talk?login=1", allow_redirects=False)
    state = parse_qs(urlparse(r.headers["Location"]).query)["state"][0]
    assert (await client.get(f"/api/kakao_talk?code=X&state={state}")).status == 200
    assert (await client.get(f"/api/kakao_talk?code=X&state={state}")).status == 400
