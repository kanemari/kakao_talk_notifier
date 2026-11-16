import json

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.kakao_talk.const import DOMAIN

from .conftest import FRIENDS_SEND_URL, MEMO_URL, UPLOAD_URL, posts


def template(body):
    return json.loads(body["template_object"])


async def test_services_registered_and_unloaded(hass, entry):
    for svc in ("send_message", "list_friends", "login"):
        assert hass.services.has_service(DOMAIN, svc)
    assert hass.services.has_service("notify", DOMAIN)
    await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service(DOMAIN, "send_message")
    assert not hass.services.has_service("notify", DOMAIN)


async def test_text_goes_to_me_and_all_friends(hass, entry, kakao_api):
    await hass.services.async_call(DOMAIN, "send_message", {"title": "T", "message": "hi"}, blocking=True)
    assert template(posts(kakao_api, MEMO_URL)[0])["text"] == "T\n\nhi"
    [friends] = posts(kakao_api, FRIENDS_SEND_URL)
    assert json.loads(friends["receiver_uuids"]) == ["u-alice", "u-bob"]


async def test_per_message_friends_and_no_self_copy(hass, entry, kakao_api):
    await hass.services.async_call(
        DOMAIN, "send_message", {"message": "hi", "friends": ["alice"], "send_to_me": False}, blocking=True
    )
    assert posts(kakao_api, MEMO_URL) == []
    [friends] = posts(kakao_api, FRIENDS_SEND_URL)
    assert json.loads(friends["receiver_uuids"]) == ["u-alice"]


async def test_friend_by_uuid(hass, entry, kakao_api):
    await hass.services.async_call(DOMAIN, "send_message", {"message": "hi", "friends": ["u-bob"]}, blocking=True)
    [friends] = posts(kakao_api, FRIENDS_SEND_URL)
    assert json.loads(friends["receiver_uuids"]) == ["u-bob"]


async def test_unknown_friend_errors(hass, entry):
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "send_message", {"message": "hi", "friends": ["Nobody"]}, blocking=True)


async def test_send_to_friends_off_per_message(hass, entry, kakao_api):
    await hass.services.async_call(DOMAIN, "send_message", {"message": "hi", "send_to_friends": False}, blocking=True)
    assert len(posts(kakao_api, MEMO_URL)) == 1
    assert posts(kakao_api, FRIENDS_SEND_URL) == []


async def test_nothing_to_do_errors(hass, entry):
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "send_message", {"message": "hi", "send_to_me": False, "send_to_friends": False}, blocking=True
        )


async def test_url_image_makes_feed_card(hass, entry, kakao_api):
    await hass.services.async_call(
        DOMAIN, "send_message", {"title": "T", "message": "m", "url": "https://example.com/a.jpg"}, blocking=True
    )
    t = template(posts(kakao_api, MEMO_URL)[0])
    assert t["object_type"] == "feed"
    assert t["content"]["image_url"] == "https://example.com/a.jpg"


async def test_url_and_image_together_rejected(hass, entry):
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "send_message", {"message": "m", "url": "https://x/a.jpg", "image": {"media_content_id": "x"}}, blocking=True
        )


async def test_media_image_is_uploaded(hass, entry, kakao_api, tmp_path, monkeypatch):
    img = tmp_path / "door.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    class Item:
        path = img

    async def fake_resolve(hass_, media_id, target):
        return Item()

    monkeypatch.setattr("homeassistant.components.media_source.async_resolve_media", fake_resolve)
    await hass.services.async_call(
        DOMAIN, "send_message",
        {"message": "m", "image": {"media_content_id": "media-source://media_source/local/door.png"}},
        blocking=True,
    )
    assert len(posts(kakao_api, UPLOAD_URL)) == 1
    t = template(posts(kakao_api, MEMO_URL)[0])
    assert t["content"]["image_url"] == "https://k.kakaocdn.net/uploaded.png"


async def test_media_image_wrong_type_rejected(hass, entry, tmp_path, monkeypatch):
    img = tmp_path / "x.gif"
    img.write_bytes(b"GIF89a")

    class Item:
        path = img

    async def fake_resolve(*a):
        return Item()

    monkeypatch.setattr("homeassistant.components.media_source.async_resolve_media", fake_resolve)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "send_message", {"message": "m", "image": "media-source://x"}, blocking=True)


async def test_list_friends_returns_response(hass, entry):
    res = await hass.services.async_call(DOMAIN, "list_friends", blocking=True, return_response=True)
    assert [f["nickname"] for f in res["friends"]] == ["Alice", "Bob"]


async def test_notify_with_photos_and_friends(hass, entry, kakao_api):
    await hass.services.async_call(
        "notify", DOMAIN,
        {"message": "m", "data": {"friends": ["Bob"], "send_to_me": False,
                                  "photo": ["https://e.com/1.jpg", {"url": "https://e.com/2.jpg"}]}},
        blocking=True,
    )
    sent = posts(kakao_api, FRIENDS_SEND_URL)
    assert len(sent) == 2  # one message per photo
    assert all(json.loads(b["receiver_uuids"]) == ["u-bob"] for b in sent)
    assert posts(kakao_api, MEMO_URL) == []


def test_image_selector_is_usable_in_the_ui():
    """A media selector without `accept` is disabled in the UI (it wants a media player)."""
    from pathlib import Path

    from homeassistant.helpers import selector
    from homeassistant.util.yaml import load_yaml

    import custom_components.kakao_talk as component

    services = load_yaml(str(Path(component.__file__).parent / "services.yaml"))
    field = services["send_message"]["fields"]["image"]
    assert field["selector"]["media"]["accept"] == ["image/jpeg", "image/png"]
    selector.selector(field["selector"])  # valid for this Home Assistant version
