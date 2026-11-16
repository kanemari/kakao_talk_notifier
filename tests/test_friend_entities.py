"""Friends as entities: pick them by name in the Actions form."""
import json
from datetime import timedelta

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.kakao_talk.const import DOMAIN

from .conftest import CONFIG, FRIENDS_SEND_URL, FRIENDS_URL, MEMO_URL, TOKEN_URL, posts


def friend_entities(hass):
    registry = er.async_get(hass)
    return sorted(
        (e for e in registry.entities.values() if e.platform == DOMAIN and e.domain == "notify"),
        key=lambda e: e.original_name or "",
    )


async def list_friends(hass):
    await hass.services.async_call(DOMAIN, "list_friends", blocking=True, return_response=True)
    await hass.async_block_till_done()


async def setup(hass, **extra):
    await hass.async_add_executor_job(lambda: open(hass.config.path("kakao.session"), "w").write("rt"))
    e = MockConfigEntry(domain=DOMAIN, data={**CONFIG, **extra}, title="K")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    return e


def mock_friends(aioclient_mock, friends):
    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_URL, json={"access_token": "at", "refresh_token": "rt"})
    aioclient_mock.post(MEMO_URL, json={"result_code": 0})
    aioclient_mock.post(FRIENDS_SEND_URL, json={"successful_receiver_uuids": []})
    aioclient_mock.get(
        FRIENDS_URL,
        json={
            "total_count": len(friends),
            "elements": [{"uuid": u, "profile_nickname": n} for u, n in friends],
        },
    )


# ------------------------------------------------------------------ creation
async def test_friends_become_entities_after_list_friends(hass, entry):
    assert friend_entities(hass) == []
    await list_friends(hass)
    entities = friend_entities(hass)
    assert [e.original_name for e in entities] == ["Alice", "Bob"]
    assert [e.unique_id for e in entities] == ["friend_u-alice", "friend_u-bob"]
    state = hass.states.get(entities[0].entity_id)
    assert state is not None and state.state != "unavailable"
    assert state.attributes["friendly_name"] == "KakaoTalk Alice"


async def test_friends_share_one_device(hass, entry):
    await list_friends(hass)
    devices = dr.async_get(hass).devices
    ours = [d for d in devices.values() if (DOMAIN, entry.entry_id) in d.identifiers]
    assert len(ours) == 1 and ours[0].name == "KakaoTalk"
    assert {e.device_id for e in friend_entities(hass)} == {ours[0].id}


async def test_no_entities_when_friends_are_off(hass, kakao_api):
    await setup(hass, send_to_friends=False)
    await list_friends_noop(hass)
    assert friend_entities(hass) == []


async def list_friends_noop(hass):
    # list_friends still works when friends sending is off; it must not create entities
    await hass.services.async_call(DOMAIN, "list_friends", blocking=True, return_response=True)
    await hass.async_block_till_done()


async def test_entities_are_removed_when_friends_are_switched_off(hass, entry):
    await list_friends(hass)
    assert len(friend_entities(hass)) == 2
    hass.config_entries.async_update_entry(entry, data={**entry.data, "send_to_friends": False})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert friend_entities(hass) == []


async def test_new_friend_appears_and_leaving_friend_becomes_unavailable(hass, entry, aioclient_mock):
    await list_friends(hass)
    mock_friends(aioclient_mock, [("u-alice", "Alice"), ("u-cara", "Cara")])
    await list_friends(hass)
    by_name = {e.original_name: e for e in friend_entities(hass)}
    assert set(by_name) == {"Alice", "Bob", "Cara"}
    assert hass.states.get(by_name["Bob"].entity_id).state == "unavailable"
    assert hass.states.get(by_name["Cara"].entity_id).state != "unavailable"
    # coming back makes it available again
    mock_friends(aioclient_mock, [("u-alice", "Alice"), ("u-bob", "Bob")])
    await list_friends(hass)
    assert hass.states.get(by_name["Bob"].entity_id).state != "unavailable"


async def test_renamed_friend_is_renamed(hass, entry, aioclient_mock):
    await list_friends(hass)
    mock_friends(aioclient_mock, [("u-alice", "Alice B."), ("u-bob", "Bob")])
    await list_friends(hass)
    assert [e.original_name for e in friend_entities(hass)] == ["Alice B.", "Bob"]


async def test_existing_entities_return_after_a_restart_without_asking_kakao(hass, entry, aioclient_mock):
    await list_friends(hass)
    ids = {e.entity_id for e in friend_entities(hass)}
    mock_friends(aioclient_mock, [])  # Kakao would return nobody, but is not asked
    aioclient_mock.mock_calls.clear()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert {e.entity_id for e in friend_entities(hass)} == ids
    for entity_id in ids:
        assert hass.states.get(entity_id).state != "unavailable"
    assert [c for c in aioclient_mock.mock_calls if str(c[1]) == FRIENDS_URL] == []


async def test_login_adds_the_friends(hass, entry, hass_client, kakao_api):
    from urllib.parse import parse_qs, urlparse

    res = await hass.services.async_call(DOMAIN, "login", blocking=True, return_response=True)
    state = parse_qs(urlparse(res["url"]).query)["state"][0]
    client = await hass_client()
    resp = await client.get(f"/api/kakao_talk?code=thecode&state={state}", allow_redirects=False)
    assert resp.status == 302
    await hass.async_block_till_done()
    assert [e.original_name for e in friend_entities(hass)] == ["Alice", "Bob"]


async def test_hourly_refresh_adds_new_friends(hass, entry, aioclient_mock):
    await list_friends(hass)
    mock_friends(aioclient_mock, [("u-alice", "Alice"), ("u-bob", "Bob"), ("u-dan", "Dan")])
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=1, minutes=1))
    await hass.async_block_till_done(wait_background_tasks=True)  # timer jobs are background tasks
    assert "Dan" in {e.original_name for e in friend_entities(hass)}


async def test_refresh_does_nothing_when_logged_out(hass, kakao_api):
    e = MockConfigEntry(domain=DOMAIN, data=dict(CONFIG), title="K")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=1, minutes=1))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert friend_entities(hass) == []
    assert [c for c in kakao_api.mock_calls if str(c[1]) == FRIENDS_URL] == []


async def test_unloading_removes_the_entities_states(hass, entry):
    await list_friends(hass)
    ids = [e.entity_id for e in friend_entities(hass)]
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    for entity_id in ids:
        assert hass.states.get(entity_id).state == "unavailable"


# ------------------------------------------------------------------ sending
def uuids_sent(kakao_api):
    return [json.loads(b["receiver_uuids"]) for b in posts(kakao_api, FRIENDS_SEND_URL)]


async def test_notify_send_message_to_a_friend_entity(hass, entry, kakao_api):
    await list_friends(hass)
    alice = friend_entities(hass)[0]
    await hass.services.async_call(
        "notify", "send_message", {"entity_id": alice.entity_id, "message": "hi", "title": "T"}, blocking=True
    )
    assert uuids_sent(kakao_api) == [["u-alice"]]
    assert posts(kakao_api, MEMO_URL) == []  # no copy to yourself
    template = json.loads(posts(kakao_api, FRIENDS_SEND_URL)[0]["template_object"])
    assert template["text"] == "T\n\nhi"


async def test_action_target_picks_friends(hass, entry, kakao_api):
    await list_friends(hass)
    alice, bob = friend_entities(hass)
    await hass.services.async_call(
        DOMAIN, "send_message",
        {"message": "hi", "entity_id": [alice.entity_id, bob.entity_id], "send_to_me": False},
        blocking=True,
    )
    assert uuids_sent(kakao_api) == [["u-alice", "u-bob"]]
    assert posts(kakao_api, MEMO_URL) == []


async def test_action_target_single_friend_and_copy_to_me(hass, entry, kakao_api):
    await list_friends(hass)
    bob = friend_entities(hass)[1]
    await hass.services.async_call(
        DOMAIN, "send_message", {"message": "hi", "entity_id": bob.entity_id}, blocking=True
    )
    assert uuids_sent(kakao_api) == [["u-bob"]]
    assert len(posts(kakao_api, MEMO_URL)) == 1  # send_to_me still defaults to on


async def test_target_and_typed_names_are_combined(hass, entry, kakao_api):
    await list_friends(hass)
    alice = friend_entities(hass)[0]
    await hass.services.async_call(
        DOMAIN, "send_message",
        {"message": "hi", "entity_id": alice.entity_id, "friends": ["Bob", "u-alice"], "send_to_me": False},
        blocking=True,
    )
    assert uuids_sent(kakao_api) == [["u-bob", "u-alice"]] or uuids_sent(kakao_api) == [["u-alice", "u-bob"]]


async def test_picking_the_device_means_all_friends(hass, entry, kakao_api):
    await list_friends(hass)
    device = next(d for d in dr.async_get(hass).devices.values() if (DOMAIN, entry.entry_id) in d.identifiers)
    await hass.services.async_call(
        DOMAIN, "send_message", {"message": "hi", "device_id": device.id, "send_to_me": False}, blocking=True
    )
    assert uuids_sent(kakao_api) == [["u-alice", "u-bob"]]


async def test_target_works_with_images(hass, entry, kakao_api):
    await list_friends(hass)
    alice = friend_entities(hass)[0]
    await hass.services.async_call(
        DOMAIN, "send_message",
        {"message": "hi", "url": "https://example.com/a.jpg", "entity_id": alice.entity_id, "send_to_me": False},
        blocking=True,
    )
    assert uuids_sent(kakao_api) == [["u-alice"]]
    assert json.loads(posts(kakao_api, FRIENDS_SEND_URL)[0]["template_object"])["object_type"] == "feed"


async def test_a_non_friend_entity_is_refused(hass, entry, kakao_api):
    hass.states.async_set("light.kitchen", "on")
    await list_friends(hass)
    with pytest.raises(ServiceValidationError, match="not a KakaoTalk friend"):
        await hass.services.async_call(
            DOMAIN, "send_message", {"message": "hi", "entity_id": "light.kitchen"}, blocking=True
        )
    assert posts(kakao_api, MEMO_URL) == [] and posts(kakao_api, FRIENDS_SEND_URL) == []


async def test_a_friend_who_left_is_reported_not_silently_skipped(hass, entry, aioclient_mock):
    await list_friends(hass)
    bob = friend_entities(hass)[1]
    mock_friends(aioclient_mock, [("u-alice", "Alice")])
    await list_friends(hass)  # Kakao no longer returns Bob
    assert hass.states.get(bob.entity_id).state == "unavailable"
    with pytest.raises(ServiceValidationError, match="None of the requested friends"):
        await hass.services.async_call(
            DOMAIN, "send_message", {"message": "hi", "entity_id": bob.entity_id, "send_to_me": False}, blocking=True
        )


async def test_friends_off_blocks_sending_to_an_entity(hass, entry, kakao_api):
    """Entities left over from before 'friends' was switched off cannot send."""
    await list_friends(hass)
    alice = friend_entities(hass)[0]
    cfg = hass.data[DOMAIN]["config"]
    cfg._send_to_friends = False
    with pytest.raises(ServiceValidationError, match="Also send to friends"):
        await hass.services.async_call(
            "notify", "send_message", {"entity_id": alice.entity_id, "message": "hi"}, blocking=True
        )


async def test_typed_friends_still_work_without_a_target(hass, entry, kakao_api):
    await hass.services.async_call(
        DOMAIN, "send_message", {"message": "hi", "friends": ["Bob"], "send_to_me": False}, blocking=True
    )
    assert uuids_sent(kakao_api) == [["u-bob"]]


# ------------------------------------------------------------------ the form
def test_action_form_offers_only_kakao_friends_as_targets():
    from pathlib import Path

    from homeassistant.util.yaml import load_yaml

    import custom_components.kakao_talk as component

    services = load_yaml(str(Path(component.__file__).parent / "services.yaml"))
    target = services["send_message"]["target"]
    assert target == {"entity": {"integration": "kakao_talk", "domain": "notify"}}
    assert "friends" in services["send_message"]["fields"]  # typing names still works
