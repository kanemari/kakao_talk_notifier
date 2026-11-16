import logging

from homeassistant.components.notify import (
    ATTR_DATA,
    ATTR_MESSAGE,
    ATTR_TITLE,
    BaseNotificationService,
)

from .const import (
    ATTR_FRIENDS,
    ATTR_LINK_TO_IMAGE,
    ATTR_LINK_URL,
    ATTR_PHOTO,
    ATTR_SEND_TO_FRIENDS,
    ATTR_SEND_TO_ME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


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
