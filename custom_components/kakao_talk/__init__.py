import logging
from typing import Any, Dict

import voluptuous as vol
from homeassistant.components.notify import (
    ATTR_DATA,
    ATTR_MESSAGE,
    ATTR_TARGET,
    ATTR_TITLE,
)
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_BUTTON_TITLE,
    CONF_CLIENT_SECRET,
    CONF_FRIENDS,
    CONF_LINK_URL,
    CONF_REDIRECT_URI,
    CONF_SEND_TO_FRIENDS,
)
from .http import (
    KakaoConfig,
    async_register_services,
    async_setup_view,
    async_unregister_services,
)
from .notify import async_send_notification

_LOGGER = logging.getLogger(__name__)

DEFAULT_SEND_TO_FRIENDS = False
ISSUE_YAML_DEPRECATED = "yaml_deprecated"

# Still accepted so existing installations keep working and can be imported.
# Deprecated: configure the integration from Settings > Devices & services.
KAKAO_TALK_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): cv.string,
        vol.Optional(CONF_CLIENT_SECRET): cv.string,
        vol.Optional(CONF_BUTTON_TITLE, default="View"): cv.string,
        vol.Required(CONF_REDIRECT_URI): cv.url,
        vol.Optional(CONF_LINK_URL): cv.url,
        vol.Optional(CONF_SEND_TO_FRIENDS, default=DEFAULT_SEND_TO_FRIENDS): cv.boolean,
        vol.Optional(CONF_FRIENDS, default=[]): vol.All(cv.ensure_list, [cv.string]),
    },
    extra=vol.PREVENT_EXTRA,
)

CONFIG_SCHEMA = vol.Schema({DOMAIN: KAKAO_TALK_SCHEMA}, extra=vol.ALLOW_EXTRA)

NOTIFY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_TITLE): cv.string,
        vol.Optional(ATTR_TARGET): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_DATA): dict,
    }
)


def entry_config(entry: ConfigEntry) -> Dict[str, Any]:
    """Settings of an entry: data, overlaid with any options."""
    return {**entry.data, **entry.options}


async def async_setup(hass: HomeAssistant, yaml_config: Dict[str, Any]) -> bool:
    hass.data.setdefault(DOMAIN, {"config": None})
    async_setup_view(hass)

    if DOMAIN in yaml_config:
        # Import once; the UI entry is the source of truth afterwards.
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data=dict(yaml_config[DOMAIN]),
            )
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_YAML_DEPRECATED,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_YAML_DEPRECATED,
            learn_more_url="https://github.com/kanemari/kakao_talk_notifier#configuration",
        )
        _LOGGER.warning(
            "Configuring kakao_talk in configuration.yaml is deprecated. Your settings "
            "are imported into Settings > Devices & services; remove the kakao_talk: "
            "block (and the notify platform: kakao_talk entry) from configuration.yaml"
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_YAML_DEPRECATED)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    config = KakaoConfig(hass, entry_config(entry))
    hass.data[DOMAIN]["config"] = config
    async_register_services(hass, config)

    async def notify_handler(call: ServiceCall):
        await async_send_notification(
            hass,
            call.data[ATTR_MESSAGE],
            call.data.get(ATTR_TITLE),
            call.data.get(ATTR_DATA),
        )

    # notify.kakao_talk, so no `notify:` block is needed in configuration.yaml.
    hass.services.async_register("notify", DOMAIN, notify_handler, schema=NOTIFY_SCHEMA)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    async_unregister_services(hass)
    hass.services.async_remove("notify", DOMAIN)
    hass.data[DOMAIN]["config"] = None
    return True
