"""WOL must work without a QTS session, including after HA restarts offline."""

import traceback
from unittest.mock import patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError
from qnap_client import QnapAuthError, QnapConnectionError


@pytest.mark.parametrize(
    "failure", [QnapConnectionError("off"), QnapAuthError("expired")]
)
async def test_offline_start_and_recovery(
    hass, mock_config_entry, mock_qnap_client, failure
):
    """The wake button loads offline; real sensors appear on the next successful poll."""
    mock_qnap_client.login.side_effect = failure
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    wake = hass.states.get("button.test_nas_wake_on_lan")
    assert wake is not None
    assert wake.state != STATE_UNAVAILABLE
    assert hass.states.get("sensor.test_nas_cpu_usage") is None
    with patch("custom_components.qnap.button.wakeonlan.send_magic_packet") as send:
        await hass.services.async_call(
            "button", "press", {"entity_id": wake.entity_id}, blocking=True
        )
        send.assert_called_once_with(
            "00:11:22:33:44:55", ip_address="192.0.2.255", port=9
        )
    mock_qnap_client.get_all.assert_not_awaited()
    mock_qnap_client.login.assert_awaited_once()
    mock_qnap_client.login.side_effect = None
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.test_nas_cpu_usage").state == "10"
    assert hass.states.get("switch.test_nas_example").state == "on"
    assert len(hass.states.async_all("button")) == 1
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    mock_qnap_client.close.assert_awaited_once_with(logout=False)


async def test_online_to_offline(hass, mock_config_entry, mock_qnap_client):
    """Losing QTS makes monitoring unavailable without disabling wake."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    mock_qnap_client.get_all.side_effect = QnapConnectionError("off")
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.test_nas_cpu_usage").state == STATE_UNAVAILABLE
    assert hass.states.get("button.test_nas_wake_on_lan").state != STATE_UNAVAILABLE


async def test_no_mac_no_wake(hass, mock_config_entry):
    """No button is advertised until physical MACs have been configured."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={})
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.states.async_all("button")


async def test_wol_error(hass, mock_config_entry):
    """Socket errors produce a translated service error with no QTS request or retry."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    with (
        patch(
            "custom_components.qnap.button.wakeonlan.send_magic_packet",
            side_effect=OSError("secret-sid"),
        ) as send,
        pytest.raises(HomeAssistantError) as error,
    ):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.test_nas_wake_on_lan"},
            blocking=True,
        )
    assert "secret-sid" not in "".join(traceback.format_exception(error.value))
    send.assert_called_once()


async def test_multiple_physical_macs(hass, mock_config_entry):
    """One invocation includes every explicitly configured NIC and custom port."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            "wol_macs": ["00:11:22:33:44:55", "00:11:22:33:44:56"],
            "broadcast_address": "192.0.2.255",
            "broadcast_port": 40000,
        },
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    with patch("custom_components.qnap.button.wakeonlan.send_magic_packet") as send:
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.test_nas_wake_on_lan"},
            blocking=True,
        )
    send.assert_called_once_with(
        "00:11:22:33:44:55", "00:11:22:33:44:56", ip_address="192.0.2.255", port=40000
    )
