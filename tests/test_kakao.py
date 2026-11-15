import json
from urllib.parse import parse_qs, urlparse
from homeassistant.setup import async_setup_component

CFG = {"kakao_talk": {"api_key": "KEY", "client_secret": "SEC",
       "redirect_uri": "https://ha.example.com:8123", "send_to_friends": True},
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

    r = await client.get("/api/kakao_talk?code=CODE")
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
    assert json.loads(sends[0][2]["template_object"])["text"] == "T\n\na&b%c+d"
    assert open(hass.config.path("kakao.session")).read() == "RT2"

    await hass.services.async_call("notify", "kakao_talk", {"message": "m", "data": {"photo": [{"url": "http://x/y.png"}]}}, blocking=True)
    assert json.loads([c for c in aioclient_mock.mock_calls if "memo" in str(c[1])][-1][2]["template_object"])["object_type"] == "feed"
