import logging

from typing import Any, Dict

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_BUTTON_TITLE,
    CONF_CLIENT_SECRET,
    CONF_FRIENDS,
    CONF_REDIRECT_URI,
    CONF_SEND_TO_FRIENDS,
)
from .http import async_register_http

_LOGGER = logging.getLogger(__name__)

DEFAULT_SEND_TO_FRIENDS = False

KAKAO_TALK_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): cv.string,
        vol.Optional(CONF_CLIENT_SECRET): cv.string,
        vol.Optional(CONF_BUTTON_TITLE, default="View"): cv.string,
        vol.Required(CONF_REDIRECT_URI): cv.string,
        vol.Optional(CONF_SEND_TO_FRIENDS, default=DEFAULT_SEND_TO_FRIENDS): cv.boolean,
        vol.Optional(CONF_FRIENDS, default=[]): vol.All(cv.ensure_list, [cv.string]),
    },
    extra=vol.PREVENT_EXTRA,
)

CONFIG_SCHEMA = vol.Schema({DOMAIN: KAKAO_TALK_SCHEMA}, extra=vol.ALLOW_EXTRA)


async def async_setup(hass: HomeAssistant, yaml_config: Dict[str, Any]) -> bool:
    config = yaml_config.get(DOMAIN)
    if not config:
        _LOGGER.error("kakao_talk is not configured in configuration.yaml")
        return False
    async_register_http(hass, config)
    return True
