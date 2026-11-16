"""Where a tapped message goes: Home Assistant (default), the image, or a custom link."""
import json

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)

from custom_components.kakao_talk.const import DOMAIN

from .conftest import CONFIG, MEMO_URL, TOKEN_URL, posts

IMAGE = "https://cdn.example.com/doorbell.jpg"
HA_LINK = "http://192.168.1.10:8123"


def template(body):
    return json.loads(body["template_object"])


def link(body):
    t = template(body)
    return (t.get("content") or t)["link"]["web_url"]


async def send(hass, **data):
    data.setdefault("message", "hi")
    data.setdefault("send_to_friends", False)
    await hass.services.async_call(DOMAIN, "send_message", data, blocking=True)


async def test_default_image_message_opens_home_assistant(hass, entry, kakao_api):
    await send(hass, url=IMAGE)
    [body] = posts(kakao_api, MEMO_URL)
    assert link(body) == HA_LINK


async def test_link_to_image_per_message(hass, entry, kakao_api):
    await send(hass, url=IMAGE, link_to_image=True)
    [body] = posts(kakao_api, MEMO_URL)
    assert link(body) == IMAGE
    assert template(body)["content"]["link"]["mobile_web_url"] == IMAGE
    assert template(body)["content"]["image_url"] == IMAGE
    assert template(body)["button_title"] == "View"


async def test_link_to_image_setting(hass, kakao_api):
    await hass.async_add_executor_job(
        lambda: open(hass.config.path("kakao.session"), "w").write("rt")
    )
    e = MockConfigEntry(domain=DOMAIN, data={**CONFIG, "link_to_image": True}, title="K")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    await send(hass, url=IMAGE)
    assert link(posts(kakao_api, MEMO_URL)[0]) == IMAGE
    # ... and a single message can opt out again
    await send(hass, url=IMAGE, link_to_image=False)
    assert link(posts(kakao_api, MEMO_URL)[1]) == HA_LINK


async def test_explicit_link_url_wins(hass, entry, kakao_api):
    await send(hass, url=IMAGE, link_to_image=True, link_url="https://example.com/door")
    [body] = posts(kakao_api, MEMO_URL)
    assert link(body) == "https://example.com/door"


async def test_text_message_custom_link(hass, entry, kakao_api):
    await send(hass, link_url="https://example.com/door")
    [body] = posts(kakao_api, MEMO_URL)
    assert template(body)["object_type"] == "text"
    assert link(body) == "https://example.com/door"


async def test_link_to_image_ignored_for_text(hass, entry, kakao_api):
    await send(hass, link_to_image=True)
    [body] = posts(kakao_api, MEMO_URL)
    assert link(body) == HA_LINK


async def test_uploaded_image_can_be_the_link(hass, entry, kakao_api, tmp_path, monkeypatch):
    img = tmp_path / "door.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    class Item:
        path = img

    async def fake_resolve(*args):
        return Item()

    monkeypatch.setattr("homeassistant.components.media_source.async_resolve_media", fake_resolve)
    await send(hass, image="media-source://media_source/local/door.png", link_to_image=True)
    [body] = posts(kakao_api, MEMO_URL)
    assert link(body) == "https://k.kakaocdn.net/uploaded.png"


def _refuse_first_memo(aioclient_mock, refuse_always=False):
    """Kakao refuses the first message (unregistered link domain), accepts the next."""
    calls = []

    async def memo(method, url, data):
        calls.append(link({"template_object": data["template_object"]}))
        if refuse_always or len(calls) == 1:
            return AiohttpClientMockResponse(
                method, url, json={"code": -2, "msg": "invalid link domain"}
            )
        return AiohttpClientMockResponse(method, url, json={"result_code": 0})

    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json={"access_token": "at", "refresh_token": "rt"})
    aioclient_mock.post(MEMO_URL, side_effect=memo)
    return calls


async def test_falls_back_to_normal_link_if_kakao_refuses(hass, entry, aioclient_mock, caplog):
    calls = _refuse_first_memo(aioclient_mock)
    await send(hass, url=IMAGE, link_to_image=True)
    assert calls == [IMAGE, HA_LINK]  # tried the image, then the normal link
    assert "Sending it again with the normal link" in caplog.text


async def test_no_retry_when_not_linking_to_image(hass, entry, aioclient_mock):
    calls = _refuse_first_memo(aioclient_mock)
    await send(hass, url=IMAGE)
    assert calls == [HA_LINK]


async def test_no_retry_for_explicit_link_url(hass, entry, aioclient_mock):
    calls = _refuse_first_memo(aioclient_mock)
    await send(hass, url=IMAGE, link_url="https://example.com/door")
    assert calls == ["https://example.com/door"]


async def test_retries_only_once(hass, entry, aioclient_mock):
    calls = _refuse_first_memo(aioclient_mock, refuse_always=True)
    await send(hass, url=IMAGE, link_to_image=True)
    assert calls == [IMAGE, HA_LINK]


async def test_fallback_also_for_friends(hass, entry, aioclient_mock):
    from .conftest import FRIENDS_SEND_URL, FRIENDS_URL

    sent = []

    async def friends_send(method, url, data):
        sent.append(link({"template_object": data["template_object"]}))
        if len(sent) == 1:
            return AiohttpClientMockResponse(method, url, json={"code": -2})
        return AiohttpClientMockResponse(method, url, json={"successful_receiver_uuids": []})

    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json={"access_token": "at"})
    aioclient_mock.get(FRIENDS_URL, json={"total_count": 1, "elements": [{"uuid": "u1", "profile_nickname": "A"}]})
    aioclient_mock.post(FRIENDS_SEND_URL, side_effect=friends_send)
    await send(hass, url=IMAGE, link_to_image=True, send_to_me=False, send_to_friends=True)
    assert sent == [IMAGE, HA_LINK]


async def test_notify_passes_link_options(hass, entry, kakao_api):
    await hass.services.async_call(
        "notify",
        DOMAIN,
        {
            "message": "m",
            "data": {
                "send_to_friends": False,
                "link_to_image": True,
                "photo": [IMAGE, {"url": "https://cdn.example.com/b.jpg", "link_url": "https://example.com/b"}],
            },
        },
        blocking=True,
    )
    links = [link(b) for b in posts(kakao_api, MEMO_URL)]
    assert links == [IMAGE, "https://example.com/b"]


async def test_option_is_saved_by_options_flow(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**CONFIG, "link_to_image": True}
    )
    await hass.async_block_till_done()
    assert entry.data["link_to_image"] is True


async def test_option_defaults_to_off(hass):
    from homeassistant import config_entries, data_entry_flow

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "k", "redirect_uri": "http://ha.local:8123"}
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["link_to_image"] is False


# ------------------------------------------------------------------ debug line / dummy link
async def test_debug_log_shows_the_link_sent(hass, entry, kakao_api, caplog):
    caplog.set_level("DEBUG", logger="custom_components.kakao_talk")
    await send(hass, url=IMAGE, link_to_image=True)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Kakao send to me:")]
    assert lines == [f"Kakao send to me: type=feed link={IMAGE} button='View'"]


async def test_debug_log_for_text_and_retry(hass, entry, aioclient_mock, caplog):
    caplog.set_level("DEBUG", logger="custom_components.kakao_talk")
    _refuse_first_memo(aioclient_mock)
    await send(hass, url=IMAGE, link_to_image=True)
    lines = [r.getMessage() for r in caplog.records if "send to me" in r.getMessage() and "type=" in r.getMessage()]
    assert lines == [
        f"Kakao send to me: type=feed link={IMAGE} button='View'",
        f"Kakao send to me (retry): type=feed link={HA_LINK} button='View'",
    ]
    await send(hass, message="plain")
    assert any("type=text link=" in r.getMessage() for r in caplog.records)


async def test_dummy_link_setting_replaces_home_assistant(hass, kakao_api):
    """A configured harmless link means no message leads to Home Assistant."""
    await hass.async_add_executor_job(
        lambda: open(hass.config.path("kakao.session"), "w").write("rt")
    )
    dummy = "https://developers.kakao.com"
    e = MockConfigEntry(domain=DOMAIN, data={**CONFIG, "link_url": dummy}, title="K")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    await send(hass, message="text")
    await send(hass, url=IMAGE)
    await send(hass, message="uploaded", url=IMAGE, link_to_image=True)
    links = [link(b) for b in posts(kakao_api, MEMO_URL)]
    assert links == [dummy, dummy, IMAGE]
    assert HA_LINK not in links


async def test_fallback_uses_the_dummy_link(hass, aioclient_mock):
    await hass.async_add_executor_job(
        lambda: open(hass.config.path("kakao.session"), "w").write("rt")
    )
    dummy = "https://developers.kakao.com"
    e = MockConfigEntry(domain=DOMAIN, data={**CONFIG, "link_url": dummy}, title="K")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    calls = _refuse_first_memo(aioclient_mock)
    await send(hass, url=IMAGE, link_to_image=True)
    assert calls == [IMAGE, dummy]
