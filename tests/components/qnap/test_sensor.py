"""Regression coverage using real entity setup and current client models."""

import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize("temperature, expected", [(None, STATE_UNKNOWN), (38, "38")])
async def test_drive_temperature(
    hass, mock_config_entry, nas_data, temperature, expected
):
    """A missing drive temperature must remain unknown rather than zero."""
    nas_data.drives[0].temperature = temperature
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.test_nas_drive_1_temperature").state == expected


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_network_missing_after_setup(hass, mock_config_entry, nas_data):
    """Disappearing NICs preserve their entities and report unknown."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    tx = "sensor.test_nas_eth0_upload"
    rx = "sensor.test_nas_eth0_download"
    assert hass.states.get(tx).state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
    assert hass.states.get(rx).state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
    nas_data.network_interfaces = []
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(tx).state == STATE_UNKNOWN
    assert hass.states.get(rx).state == STATE_UNKNOWN
