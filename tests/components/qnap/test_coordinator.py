"""Regression tests for monitoring recovery and power session ownership."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from qnap_client import QnapAuthError, QnapConnectionError

from homeassistant.const import CONF_SSL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.qnap.coordinator import QnapCoordinator


@pytest.mark.parametrize("verify_ssl", [True, False])
async def test_control_inherits_https_and_verification(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_qnap_client: MagicMock,
    verify_ssl: bool,
) -> None:
    """Explicit omission stays per-entry and HTTPS remains selected."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_SSL: True, CONF_VERIFY_SSL: verify_ssl},
    )
    with patch(
        "custom_components.qnap.coordinator.QnapClient", return_value=mock_qnap_client
    ) as factory:
        coordinator = QnapCoordinator(hass, mock_config_entry)
        await coordinator.async_power_action("shutdown")
    assert factory.call_count == 2
    for call in factory.call_args_list:
        assert call.kwargs[CONF_SSL] is True
        assert call.kwargs[CONF_VERIFY_SSL] is verify_ssl


@pytest.mark.parametrize("expired_as_empty_identity", [False, True])
async def test_expired_session_renews_once_using_public_api(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_qnap_client: MagicMock,
    expired_as_empty_identity: bool,
) -> None:
    """HTTP auth failures and empty QTS identities trigger one bounded login."""
    mock_config_entry.add_to_hass(hass)
    coordinator = QnapCoordinator(hass, mock_config_entry)
    info = mock_qnap_client.get_system_info.return_value
    expired = (
        replace(info, serial_number="")
        if expired_as_empty_identity
        else QnapAuthError("private-response")
    )
    mock_qnap_client.get_system_info.side_effect = [expired, info]
    result = await coordinator._async_update_data()
    mock_qnap_client.login.assert_awaited_once_with()
    assert mock_qnap_client.get_system_info.await_count == 2
    mock_qnap_client.get_all.assert_awaited_once_with()
    mock_qnap_client.logout.assert_not_awaited()
    mock_qnap_client.shutdown.assert_not_awaited()
    mock_qnap_client.reboot.assert_not_awaited()
    assert result.system_info is info


@pytest.mark.parametrize("renewal_failure", ["empty_identity", "auth_error"])
async def test_failed_renewal_stops_without_energy_or_another_login(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_qnap_client: MagicMock,
    renewal_failure: str,
) -> None:
    """An invalid session cannot become successful default-valued sensor data."""
    mock_config_entry.add_to_hass(hass)
    coordinator = QnapCoordinator(hass, mock_config_entry)
    info = mock_qnap_client.get_system_info.return_value
    if renewal_failure == "empty_identity":
        mock_qnap_client.get_system_info.return_value = replace(info, serial_number="")
    else:
        mock_qnap_client.get_system_info.side_effect = QnapAuthError("private-response")
    with pytest.raises(UpdateFailed) as raised:
        await coordinator._async_update_data()
    assert "private-response" not in str(raised.value)
    mock_qnap_client.login.assert_awaited_once_with()
    assert mock_qnap_client.get_system_info.await_count == 2
    mock_qnap_client.get_all.assert_not_awaited()
    mock_qnap_client.shutdown.assert_not_awaited()
    mock_qnap_client.reboot.assert_not_awaited()


async def test_different_device_identity_is_rejected(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_qnap_client: MagicMock,
) -> None:
    """Data from a different NAS is never attached to the configured device."""
    mock_config_entry.add_to_hass(hass)
    coordinator = QnapCoordinator(hass, mock_config_entry)
    info = mock_qnap_client.get_system_info.return_value
    mock_qnap_client.get_system_info.return_value = replace(
        info, serial_number="OTHER-NAS"
    )
    with pytest.raises(UpdateFailed, match="identity does not match"):
        await coordinator._async_update_data()
    mock_qnap_client.login.assert_not_awaited()
    mock_qnap_client.get_all.assert_not_awaited()


async def test_offline_probe_does_not_publish_aggregate_defaults(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_qnap_client: MagicMock,
) -> None:
    """A connection failure ends this poll before the aggregate masks errors."""
    mock_config_entry.add_to_hass(hass)
    coordinator = QnapCoordinator(hass, mock_config_entry)
    mock_qnap_client.get_system_info.side_effect = QnapConnectionError(
        "private-response"
    )
    with pytest.raises(UpdateFailed) as raised:
        await coordinator._async_update_data()
    assert "private-response" not in str(raised.value)
    mock_qnap_client.get_all.assert_not_awaited()
    mock_qnap_client.login.assert_not_awaited()


@pytest.mark.parametrize("serial_number", ["", "OTHER-NAS"])
async def test_aggregate_failure_after_probe_is_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_qnap_client: MagicMock,
    serial_number: str,
) -> None:
    """A successful earlier probe cannot conceal aggregate identity failure."""
    mock_config_entry.add_to_hass(hass)
    coordinator = QnapCoordinator(hass, mock_config_entry)
    data = mock_qnap_client.get_all.return_value
    mock_qnap_client.get_all.return_value = replace(
        data, system_info=replace(data.system_info, serial_number=serial_number)
    )
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    mock_qnap_client.get_system_info.assert_awaited_once_with()
    mock_qnap_client.get_all.assert_awaited_once_with()
    mock_qnap_client.login.assert_not_awaited()


async def test_close_waits_for_monitoring_and_prevents_new_reads(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_qnap_client: MagicMock,
) -> None:
    """Unload waits for an in-flight read and never reopens its HTTP session."""
    mock_config_entry.add_to_hass(hass)
    coordinator = QnapCoordinator(hass, mock_config_entry)
    data = mock_qnap_client.get_all.return_value
    started = asyncio.Event()
    release = asyncio.Event()

    async def wait_for_data():
        started.set()
        await release.wait()
        return data

    mock_qnap_client.get_all.side_effect = wait_for_data
    reading = asyncio.create_task(coordinator._async_update_data())
    await started.wait()
    closing = asyncio.create_task(coordinator.async_close())
    await asyncio.sleep(0)
    try:
        assert not closing.done()
        mock_qnap_client.close.assert_not_awaited()
    finally:
        release.set()
        await reading
        await closing
    await coordinator.async_close()
    mock_qnap_client.close.assert_awaited_once_with(logout=False)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    mock_qnap_client.get_system_info.assert_awaited_once_with()


async def test_unload_closes_owned_client_without_logout(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_qnap_client: MagicMock,
) -> None:
    """Unloading after shutdown needs no extra request to an offline NAS."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    mock_qnap_client.close.assert_awaited_once_with(logout=False)
    mock_qnap_client.logout.assert_not_awaited()


async def test_failed_setup_closes_owned_client_without_logout(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_qnap_client: MagicMock,
) -> None:
    """Failed first refresh releases its session while preserving the cause."""
    mock_config_entry.add_to_hass(hass)
    mock_qnap_client.login.side_effect = QnapAuthError("private-response")
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    mock_qnap_client.close.assert_awaited_once_with(logout=False)
    mock_qnap_client.logout.assert_not_awaited()
