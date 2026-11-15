import logging

from homeassistant.components.notify import (
    ATTR_DATA,
    ATTR_MESSAGE,
    ATTR_TITLE,
    BaseNotificationService,
)

from .const import ATTR_PHOTO, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_get_service(hass, config, discovery_info=None):
    """Get the KakaoTalk notification service."""
    return KakaoTalkNotificationService(hass)


class KakaoTalkNotificationService(BaseNotificationService):
    def __init__(self, hass):
        """Initialize the service."""
        self.hass = hass

    async def async_send_message(self, message="", **kwargs):
        service_data = {}
        if kwargs.get(ATTR_TITLE):
            service_data[ATTR_TITLE] = kwargs[ATTR_TITLE]
        if message:
            service_data[ATTR_MESSAGE] = message

        data = kwargs.get(ATTR_DATA)
        if data is not None and ATTR_PHOTO in data:
            photos = data[ATTR_PHOTO]
            photos = photos if isinstance(photos, list) else [photos]
            for photo_data in photos:
                if isinstance(photo_data, str):
                    photo_data = {"url": photo_data}
                await self.hass.services.async_call(
                    DOMAIN,
                    "send_message",
                    service_data={**service_data, **photo_data},
                    blocking=True,
                )
            return

        _LOGGER.debug("KAKAOTALK NOTIFIER calling %s.send_message with %s", DOMAIN, service_data)
        await self.hass.services.async_call(
            DOMAIN, "send_message", service_data=service_data, blocking=True
        )
