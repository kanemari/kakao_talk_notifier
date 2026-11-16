from homeassistant import config_entries, data_entry_flow
from homeassistant.setup import async_setup_component
from homeassistant.helpers import issue_registry as ir

from custom_components.kakao_talk.const import DOMAIN

from .conftest import CONFIG


async def test_user_flow_creates_entry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"api_key": " key ", "redirect_uri": "http://ha.local:8123/", "button_title": "Open"},
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["api_key"] == "key"
    assert result["data"]["redirect_uri"] == "http://ha.local:8123"
    assert result["data"]["button_title"] == "Open"
    assert result["data"]["send_to_friends"] is False


async def test_user_flow_rejects_bad_url(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "key", "redirect_uri": "not a url"}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"redirect_uri": "invalid_url"}


async def test_single_instance(hass, entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.ABORT


async def test_yaml_is_imported_with_deprecation_issue(hass, kakao_api):
    yaml = {DOMAIN: {"api_key": "yk", "client_secret": "ys", "redirect_uri": "http://1.2.3.4:8123",
                     "send_to_friends": True, "friends": ["Alice"]}}
    assert await async_setup_component(hass, DOMAIN, yaml)
    await hass.async_block_till_done()
    [entry] = hass.config_entries.async_entries(DOMAIN)
    assert entry.data["api_key"] == "yk"
    assert entry.data["friends"] == ["Alice"]
    assert entry.data["send_to_friends"] is True
    assert ir.async_get(hass).async_get_issue(DOMAIN, "yaml_deprecated")


async def test_yaml_ignored_when_entry_exists(hass, entry):
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: {"api_key": "other", "redirect_uri": "http://x:8123"}})
    await hass.async_block_till_done()
    [entry] = hass.config_entries.async_entries(DOMAIN)
    assert entry.data["api_key"] == CONFIG["api_key"]


async def test_no_issue_without_yaml(hass, entry):
    assert not ir.async_get(hass).async_get_issue(DOMAIN, "yaml_deprecated")


async def test_options_flow_updates_and_reloads(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    # friends were fetched from the (mocked) API for the picker
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**CONFIG, "button_title": "Look", "friends": ["Alice"]},
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.data["button_title"] == "Look"
    assert entry.data["friends"] == ["Alice"]
    assert hass.services.has_service(DOMAIN, "send_message")  # reloaded and re-registered
