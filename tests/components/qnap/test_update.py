"""Regression tests for the read-only firmware entity."""

import pytest
from homeassistant.const import STATE_OFF, STATE_ON


@pytest.mark.parametrize(
    "latest, expected", [(None, STATE_OFF), ("5.2.0.1234", STATE_ON)]
)
async def test_firmware(hass, mock_config_entry, nas_data, latest, expected):
    """Firmware state and installed version use the client dataclass."""
    nas_data.firmware.latest_version = latest
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("update.test_nas_firmware")
    assert state.state == expected
    assert state.attributes["installed_version"] == "5.1.0.2548"


async def test_firmware_unavailable_data(hass, mock_config_entry, nas_data):
    """An optional firmware section can be absent without breaking setup."""
    nas_data.firmware = None
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert (
        hass.states.get("update.test_nas_firmware").attributes["installed_version"]
        is None
    )
