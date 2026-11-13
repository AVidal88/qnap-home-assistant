"""Tests for QNAP update platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_firmware_update_no_update(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Update entity is off when the model has no newer firmware version."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("update.test_nas_firmware")
    assert state is not None
    assert state.state == STATE_OFF
    assert state == snapshot


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_firmware_update_available(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Update entity state is ON when a newer firmware version is available."""
    mock_qnap_client.get_all.return_value.firmware.latest_version = (
        "5.2.0.1234 Build 20240101"
    )

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("update.test_nas_firmware")
    assert state is not None
    assert state.state == STATE_ON
    assert state == snapshot


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_firmware_update_unavailable(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Missing firmware data leaves the update entity unknown."""
    mock_qnap_client.get_all.return_value.firmware = None

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("update.test_nas_firmware")
    assert state is not None
    assert state.state == STATE_UNKNOWN


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_firmware_installed_version(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The installed version reflects the public firmware model."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("update.test_nas_firmware")
    assert state is not None
    assert state.attributes["installed_version"] == "5.1.0.2548"
