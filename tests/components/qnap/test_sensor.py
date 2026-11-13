"""Tests for QNAP sensor platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant

# ---------------------------------------------------------------------------
# Drive temperature sensor
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_drive_temp_sensor_none_returns_unknown(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An unavailable drive temperature remains unknown."""
    mock_qnap_client.get_all.return_value.drives[0].temperature = None

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_nas_drive_0_temperature")
    assert state is not None
    assert state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE), (
        f"Expected unknown/unavailable for None temp, got: {state.state!r}"
    )
    assert state.state != "0", "drive_temp must not return 0 when temp_c is None"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_drive_temp_sensor_with_value(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Drive temperature exposes the value from the public client model."""
    mock_qnap_client.get_all.return_value.drives[0].temperature = 38

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_nas_drive_0_temperature")
    assert state is not None
    assert state.state == "38"


# ---------------------------------------------------------------------------
# Network bandwidth sensors
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_network_sensor_nic_missing_from_bandwidth(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Existing bandwidth sensors become unknown when their interface disappears."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_qnap_client.get_all.return_value.network_interfaces = []
    await mock_config_entry.runtime_data.async_request_refresh()
    await hass.async_block_till_done()

    tx_state = hass.states.get("sensor.test_nas_eth0_upload")
    rx_state = hass.states.get("sensor.test_nas_eth0_download")

    assert tx_state is not None, "network_tx sensor entity should exist"
    assert tx_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE), (
        f"Expected unknown/unavailable for missing bandwidth, got tx={tx_state.state!r}"
    )

    assert rx_state is not None, "network_rx sensor entity should exist"
    assert rx_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE), (
        f"Expected unknown/unavailable for missing bandwidth, got rx={rx_state.state!r}"
    )


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_network_sensor_nic_in_bandwidth(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Network tx/rx sensors return a valid value when NIC is present in bandwidth."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    tx_state = hass.states.get("sensor.test_nas_eth0_upload")
    rx_state = hass.states.get("sensor.test_nas_eth0_download")

    assert tx_state is not None
    assert tx_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN), (
        f"Expected a valid bandwidth value for tx, got: {tx_state.state!r}"
    )

    assert rx_state is not None
    assert rx_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN), (
        f"Expected a valid bandwidth value for rx, got: {rx_state.state!r}"
    )
