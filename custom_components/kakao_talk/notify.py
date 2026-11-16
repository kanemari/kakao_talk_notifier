import logging
from datetime import timedelta

from homeassistant.components.notify import (
    ATTR_DATA,
    ATTR_MESSAGE,
    ATTR_TITLE,
    BaseNotificationService,
    NotifyEntity,
    NotifyEntityFeature,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    ATTR_FRIENDS,
    ATTR_LINK_TO_IMAGE,
    ATTR_LINK_URL,
    ATTR_PHOTO,
    ATTR_SEND_TO_FRIENDS,
    ATTR_SEND_TO_ME,
    DOMAIN,
    FRIEND_UNIQUE_PREFIX,
)

_LOGGER = logging.getLogger(__name__)

# How often the friends list is fetched to add new friends and notice ones that left.
FRIEND_REFRESH_INTERVAL = timedelta(hours=1)


async def async_send_notification(hass, message="", title=None, data=None):
    """Send a notify-style message through kakao_talk.send_message."""
    service_data = {}
    if title:
        service_data[ATTR_TITLE] = title
    if message:
        service_data[ATTR_MESSAGE] = message

    if data:
        for key in (
            ATTR_FRIENDS,
            ATTR_LINK_TO_IMAGE,
            ATTR_LINK_URL,
            ATTR_SEND_TO_FRIENDS,
            ATTR_SEND_TO_ME,
        ):
            if key in data:
                service_data[key] = data[key]
    if data is not None and ATTR_PHOTO in data:
        photos = data[ATTR_PHOTO]
        photos = photos if isinstance(photos, list) else [photos]
        for photo_data in photos:
            if isinstance(photo_data, str):
                photo_data = {"url": photo_data}
            await hass.services.async_call(
                DOMAIN,
                "send_message",
                service_data={**service_data, **photo_data},
                blocking=True,
            )
        return

    _LOGGER.debug("KAKAOTALK NOTIFIER calling %s.send_message with %s", DOMAIN, service_data)
    await hass.services.async_call(
        DOMAIN, "send_message", service_data=service_data, blocking=True
    )


async def async_get_service(hass, config, discovery_info=None):
    """Legacy `notify: - platform: kakao_talk` (deprecated, see the integration page)."""
    return KakaoTalkNotificationService(hass)


class KakaoTalkNotificationService(BaseNotificationService):
    def __init__(self, hass):
        """Initialize the service."""
        self.hass = hass

    async def async_send_message(self, message="", **kwargs):
        await async_send_notification(
            self.hass, message, kwargs.get(ATTR_TITLE), kwargs.get(ATTR_DATA)
        )


# ---------------------------------------------------------------- friend entities
async def async_setup_entry(hass, entry, async_add_entities):
    """One notify entity per friend, so friends can be picked by name in the UI.

    Entities that already exist are restored at once; new friends are added whenever the
    friends list is fetched (after a login, by kakao_talk.list_friends, when sending to
    friends, and about once an hour).
    """
    config = hass.data[DOMAIN]["config"]
    registry = er.async_get(hass)
    known = [
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "notify" and (e.unique_id or "").startswith(FRIEND_UNIQUE_PREFIX)
    ]

    if not config.send_to_friends:
        # Friends are switched off: do not leave friend entities behind.
        for e in known:
            registry.async_remove(e.entity_id)
        return

    entities = {}

    def build(uuid, name):
        entity = KakaoFriend(config, entry, uuid, name)
        entities[uuid] = entity
        return entity

    async_add_entities(
        [
            build(e.unique_id[len(FRIEND_UNIQUE_PREFIX):], e.original_name or e.name or "Friend")
            for e in known
        ]
    )

    @callback
    def friends_changed(friends):
        live = {f["uuid"] for f in friends}
        new = []
        for friend in friends:
            name = friend.get("nickname") or "Friend"
            entity = entities.get(friend["uuid"])
            if entity is None:
                new.append(build(friend["uuid"], name))
            else:
                entity.update_from_kakao(name, present=True)
        if new:
            async_add_entities(new)
        for uuid, entity in entities.items():
            if uuid not in live:
                entity.update_from_kakao(None, present=False)

    entry.async_on_unload(config.add_friends_listener(friends_changed))

    async def refresh(_now):
        await config.async_refresh_friends()

    entry.async_on_unload(
        async_track_time_interval(hass, refresh, FRIEND_REFRESH_INTERVAL)
    )


class KakaoFriend(NotifyEntity):
    """A KakaoTalk friend. Sending a message to this entity messages only that friend."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, config, entry, uuid, name):
        self._config = config
        self._uuid = uuid
        self._present = True
        self._attr_name = name
        self._attr_unique_id = FRIEND_UNIQUE_PREFIX + uuid
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="KakaoTalk",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self):
        """False once Kakao no longer returns this friend."""
        return self._present

    @callback
    def update_from_kakao(self, name, present):
        """Apply the result of fetching the friends list."""
        changed = present != self._present
        self._present = present
        if name and name != self._attr_name:
            self._attr_name = name
            changed = True
            if self.registry_entry is not None:
                er.async_get(self.hass).async_update_entity(
                    self.entity_id, original_name=name
                )
        if changed and self.hass is not None and self.entity_id:
            self.async_write_ha_state()

    async def async_send_message(self, message, title=None):
        text = f"{title}\n\n{message}" if title else message
        await self._config.async_send_text(
            text, friends=[self._uuid], send_to_friends=True, send_to_me=False
        )
