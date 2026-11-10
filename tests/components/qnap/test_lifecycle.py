"""Config flows and coordinator lifecycle without a reachable physical NAS."""

import logging
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from qnap_client import QnapAuthError, QnapConnectionError

from custom_components.qnap import config_flow
from custom_components.qnap.const import DOMAIN
from custom_components.qnap.coordinator import UPDATE_INTERVAL

CANARY_SID = "private-session-canary"
CANARY_PASSWORD = "private-password-canary"


async def test_user_flow_success(hass, mock_config_entry, nas_data):
    """An initial online setup stores the real serial and connection settings."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    user_input = dict(mock_config_entry.data)
    with patch("custom_components.qnap.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=user_input
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == nas_data.system_info.name
    assert result["data"] == user_input
    assert result["result"].unique_id == nas_data.system_info.serial_number
    config_flow.QnapClient.return_value.get_system_info.assert_awaited_once()


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        (QnapAuthError(f"{CANARY_SID} {CANARY_PASSWORD}"), "invalid_auth"),
        (QnapConnectionError(f"{CANARY_SID} {CANARY_PASSWORD}"), "cannot_connect"),
        (RuntimeError(f"{CANARY_SID} {CANARY_PASSWORD}"), "unknown"),
    ],
)
async def test_user_flow_errors_are_safe(
    hass, mock_config_entry, caplog, failure, expected_error
):
    """Failed validation stays in the form and never logs secret error details."""
    config_flow.QnapClient.return_value.get_system_info.side_effect = failure
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=dict(mock_config_entry.data)
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": expected_error}
    assert not hass.config_entries.async_entries(DOMAIN)
    assert CANARY_SID not in caplog.text
    assert CANARY_PASSWORD not in caplog.text
    config_flow.QnapClient.return_value.get_system_info.assert_awaited_once()


@pytest.mark.parametrize("serial_matches", [True, False])
async def test_reconfigure_preserves_options_and_identity(
    hass, mock_config_entry, nas_data, serial_matches
):
    """Reconfiguration preserves WOL settings and refuses a different NAS."""
    mock_config_entry.add_to_hass(hass)
    original_data = dict(mock_config_entry.data)
    original_options = dict(mock_config_entry.options)
    user_input = {**original_data, "host": "198.51.100.10"}
    if not serial_matches:
        config_flow.QnapClient.return_value.get_system_info.return_value = replace(
            nas_data.system_info, serial_number="DIFFERENT-NAS"
        )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )
    assert result["type"] == FlowResultType.FORM
    with patch("custom_components.qnap.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=user_input
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == (
        "reconfigure_successful" if serial_matches else "unique_id_mismatch"
    )
    assert mock_config_entry.data == (user_input if serial_matches else original_data)
    assert mock_config_entry.options == original_options
    assert mock_config_entry.unique_id == nas_data.system_info.serial_number


async def test_online_unload_and_reload(
    hass, mock_config_entry, mock_qnap_client, caplog
):
    """Unload stops polling, closes locally, and reload creates no duplicate entities."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = mock_config_entry.runtime_data
    states_before = set(hass.states.async_entity_ids())
    registry = er.async_get(hass)
    registered_before = {
        (entity.entity_id, entity.unique_id)
        for entity in registry.entities.values()
        if entity.config_entry_id == mock_config_entry.entry_id
    }
    assert states_before
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    mock_qnap_client.close.assert_awaited_once_with(logout=False)

    async_fire_time_changed(
        hass, dt_util.utcnow() + UPDATE_INTERVAL + timedelta(seconds=1)
    )
    await hass.async_block_till_done()
    mock_qnap_client.get_all.assert_awaited_once()

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.runtime_data is not coordinator
    assert set(hass.states.async_entity_ids()) == states_before
    assert {
        (entity.entity_id, entity.unique_id)
        for entity in registry.entities.values()
        if entity.config_entry_id == mock_config_entry.entry_id
    } == registered_before
    assert mock_qnap_client.login.await_count == 2
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_qnap_client.close.await_count == 2
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


async def test_offline_recovers_on_scheduled_poll(
    hass, mock_config_entry, mock_qnap_client, caplog
):
    """An offline entry retains listeners that poll and create real entities later."""
    mock_qnap_client.login.side_effect = [
        QnapConnectionError(f"{CANARY_SID} {CANARY_PASSWORD}"),
        None,
    ]
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("button.test_nas_wake_on_lan").state != STATE_UNAVAILABLE
    assert hass.states.get("sensor.test_nas_cpu_usage") is None
    mock_qnap_client.get_all.assert_not_awaited()

    # Exercise the actual interval callback, rather than calling async_refresh.
    async_fire_time_changed(
        hass, dt_util.utcnow() + UPDATE_INTERVAL + timedelta(seconds=1)
    )
    await hass.async_block_till_done()
    assert mock_qnap_client.login.await_count == 2
    mock_qnap_client.get_all.assert_awaited_once()
    assert hass.states.get("sensor.test_nas_cpu_usage").state == "10"
    assert hass.states.get("switch.test_nas_example").state == "on"
    assert len(hass.states.async_all("button")) == 1
    assert CANARY_SID not in caplog.text
    assert CANARY_PASSWORD not in caplog.text
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    mock_qnap_client.close.assert_awaited_once_with(logout=False)
