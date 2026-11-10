"""Options configure WOL locally without probing QTS."""

from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.qnap.config_flow import (
    normalize_broadcast_address,
    normalize_mac_addresses,
)


@pytest.mark.parametrize(
    "mac",
    [
        "00:00:00:00:00:00",
        "ff:ff:ff:ff:ff:ff",
        "01:00:5e:00:00:01",
        "garbage",
        "00:11-22:33:44:55",
        "00112233445g",
    ],
)
def test_invalid_mac(mac):
    with pytest.raises(ValueError):
        normalize_mac_addresses([mac])


def test_normalize_macs():
    assert normalize_mac_addresses(
        ["00-11-22-AA-BB-CC", "001122aabbcc", "00:11:22:aa:bb:cc"]
    ) == ["00:11:22:aa:bb:cc"]
    assert normalize_mac_addresses([]) == []


@pytest.mark.parametrize(
    "address", ["::1", "nas.local", "0.0.0.0", "127.0.0.1", "224.0.0.1", "192.0.2.999"]
)
def test_invalid_broadcast(address):
    with pytest.raises(ValueError):
        normalize_broadcast_address(address)


@pytest.mark.parametrize("address", ["255.255.255.255", "192.0.2.255"])
def test_broadcast(address):
    assert normalize_broadcast_address(address) == address


async def test_options_offline(hass, mock_config_entry, mock_qnap_client):
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    with patch("custom_components.qnap.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                "wol_macs": ["00-11-22-AA-BB-CC", "001122AABBCC"],
                "broadcast_address": "192.0.2.255",
                "broadcast_port": 40000,
            },
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options["wol_macs"] == ["00:11:22:aa:bb:cc"]
    assert mock_config_entry.options["broadcast_port"] == 40000
    mock_qnap_client.login.assert_not_awaited()


async def test_invalid_options(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "wol_macs": ["ff:ff:ff:ff:ff:ff"],
            "broadcast_address": "192.0.2.255",
            "broadcast_port": 9,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"wol_macs": "invalid_mac"}


async def test_clear_macs(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "wol_macs": [],
            "broadcast_address": "255.255.255.255",
            "broadcast_port": 9,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options["wol_macs"] == []
