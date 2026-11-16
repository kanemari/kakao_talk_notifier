"""Config flow: set up and change KakaoTalk from the UI, and import configuration.yaml."""
import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_API_KEY,
    CONF_BUTTON_TITLE,
    CONF_CLIENT_SECRET,
    CONF_FRIENDS,
    CONF_INVITE_REDIRECT_URI,
    CONF_LINK_TO_IMAGE,
    CONF_LINK_URL,
    CONF_REDIRECT_URI,
    CONF_SEND_TO_FRIENDS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_BUTTON_TITLE = "View"


def _text(kind=TextSelectorType.TEXT, **kwargs):
    return TextSelector(TextSelectorConfig(type=kind, **kwargs))


def _schema(values: Dict[str, Any], friend_choices=None) -> vol.Schema:
    """Form schema, prefilled from `values`."""

    def suggest(key):
        return {"suggested_value": values.get(key)}

    if friend_choices is None:
        friends = _text(multiple=True)
    else:
        known = sorted(set(friend_choices) | set(values.get(CONF_FRIENDS) or []))
        friends = SelectSelector(
            SelectSelectorConfig(options=known, multiple=True, custom_value=True)
        )

    return vol.Schema(
        {
            vol.Required(CONF_API_KEY, description=suggest(CONF_API_KEY)): _text(),
            vol.Optional(
                CONF_CLIENT_SECRET, description=suggest(CONF_CLIENT_SECRET)
            ): _text(TextSelectorType.PASSWORD),
            vol.Required(
                CONF_REDIRECT_URI, description=suggest(CONF_REDIRECT_URI)
            ): _text(TextSelectorType.URL),
            vol.Optional(CONF_LINK_URL, description=suggest(CONF_LINK_URL)): _text(
                TextSelectorType.URL
            ),
            vol.Optional(
                CONF_LINK_TO_IMAGE, default=bool(values.get(CONF_LINK_TO_IMAGE))
            ): BooleanSelector(),
            vol.Optional(
                CONF_INVITE_REDIRECT_URI, description=suggest(CONF_INVITE_REDIRECT_URI)
            ): _text(TextSelectorType.URL),
            vol.Optional(
                CONF_BUTTON_TITLE,
                default=values.get(CONF_BUTTON_TITLE) or DEFAULT_BUTTON_TITLE,
            ): _text(),
            vol.Optional(
                CONF_SEND_TO_FRIENDS, default=bool(values.get(CONF_SEND_TO_FRIENDS))
            ): BooleanSelector(),
            vol.Optional(CONF_FRIENDS, description=suggest(CONF_FRIENDS)): friends,
        }
    )


def _clean(user_input: Dict[str, Any]) -> Dict[str, Any]:
    """Drop empty optional values and normalise."""
    data = {k: v for k, v in user_input.items() if v not in (None, "", [])}
    data[CONF_API_KEY] = data[CONF_API_KEY].strip()
    data[CONF_REDIRECT_URI] = data[CONF_REDIRECT_URI].strip().rstrip("/")
    if CONF_LINK_URL in data:
        data[CONF_LINK_URL] = data[CONF_LINK_URL].strip()
    if CONF_INVITE_REDIRECT_URI in data:
        data[CONF_INVITE_REDIRECT_URI] = data[CONF_INVITE_REDIRECT_URI].strip().rstrip("/")
    data[CONF_FRIENDS] = [str(f).strip() for f in data.get(CONF_FRIENDS, []) if str(f).strip()]
    data.setdefault(CONF_BUTTON_TITLE, DEFAULT_BUTTON_TITLE)
    data.setdefault(CONF_SEND_TO_FRIENDS, False)
    data.setdefault(CONF_LINK_TO_IMAGE, False)
    return data


def _validate(data: Dict[str, Any]) -> Dict[str, str]:
    errors = {}
    for key in (CONF_REDIRECT_URI, CONF_LINK_URL, CONF_INVITE_REDIRECT_URI):
        if key in data:
            try:
                cv.url(data[key])
            except vol.Invalid:
                errors[key] = "invalid_url"
    if not data.get(CONF_API_KEY):
        errors[CONF_API_KEY] = "required"
    return errors


class KakaoTalkConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors = {}
        if user_input is not None:
            data = _clean(user_input)
            errors = _validate(data)
            if not errors:
                return self.async_create_entry(title="KakaoTalk", data=data)
        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input or {}), errors=errors
        )

    async def async_step_import(self, import_config: Dict[str, Any]):
        """Import the deprecated configuration.yaml settings, once."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        data = _clean(dict(import_config))
        if _validate(data):
            _LOGGER.error("The kakao_talk settings in configuration.yaml are invalid; not imported")
            return self.async_abort(reason="invalid_import")
        _LOGGER.info("Imported kakao_talk settings from configuration.yaml")
        return self.async_create_entry(title="KakaoTalk", data=data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        return KakaoTalkOptionsFlow()


class KakaoTalkOptionsFlow(OptionsFlow):
    """Change every setting from the UI. The entry reloads when saved."""

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None):
        current = {**self.config_entry.data, **self.config_entry.options}
        errors = {}
        if user_input is not None:
            data = _clean(user_input)
            errors = _validate(data)
            if not errors:
                self.hass.config_entries.async_update_entry(self.config_entry, data=data, options={})
                return self.async_create_entry(data={})
            current = user_input
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(current, await self._friend_choices()),
            errors=errors,
        )

    async def _friend_choices(self):
        """Nicknames Kakao returns, to pick from. None when they cannot be fetched."""
        config = self.hass.data.get(DOMAIN, {}).get("config")
        if config is None or not config.send_to_friends:
            return None
        try:
            friends = await config.async_list_friends()
        except Exception as exception:  # a failed lookup must not block the form
            _LOGGER.debug("Could not list friends for the options form: %s", exception)
            return None
        return [f["nickname"] for f in friends if f.get("nickname")] or None
