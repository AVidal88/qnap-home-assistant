"""Config flow tests using the asynchronous public client API."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from qnap_client import QnapAuthError, QnapConnectionError, QnapTimeoutError

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.qnap.const import DOMAIN, WAKE_ON_LAN_CONFIG_FLOW_URL

from .conftest import TEST_NAS_NAME, TEST_SERIAL


@pytest.mark.parametrize("verify_ssl", [True, False])
async def test_user_flow_uses_public_client_and_existing_tls_settings(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    qnap_connect: MagicMock,
    mock_setup_entry: MagicMock,
    verify_ssl: bool,
) -> None:
    """Setup verifies identity without a power action or WOL configuration."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["description_placeholders"] == {
        "wake_on_lan_url": WAKE_ON_LAN_CONFIG_FLOW_URL
    }
    user_input = {
        key: value for key, value in mock_config_entry.data.items() if key != "timeout"
    }
    user_input.update(ssl=True, port=443, verify_ssl=verify_ssl)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=user_input
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TEST_NAS_NAME
    assert result["result"].unique_id == TEST_SERIAL
    assert result["data"] == user_input
    qnap_connect.get_system_info.assert_awaited_once_with()
    qnap_connect.shutdown.assert_not_awaited()
    qnap_connect.reboot.assert_not_awaited()
    qnap_connect.__aenter__.assert_awaited_once_with()
    qnap_connect.__aexit__.assert_awaited_once()
    assert not hass.config_entries.async_entries("wake_on_lan")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (QnapAuthError("invalid authentication"), "invalid_auth"),
        (QnapConnectionError("connection unavailable"), "cannot_connect"),
        (QnapTimeoutError("timeout"), "cannot_connect"),
    ],
)
async def test_connection_errors_remain_in_the_form(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    qnap_connect: MagicMock,
    error: Exception,
    expected: str,
) -> None:
    """Failures in the public read-only validation preserve standard errors."""
    qnap_connect.get_system_info.side_effect = error
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={
            key: value
            for key, value in mock_config_entry.data.items()
            if key != "timeout"
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    qnap_connect.shutdown.assert_not_awaited()
    qnap_connect.reboot.assert_not_awaited()


async def test_duplicate_device_is_aborted(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    qnap_connect: MagicMock,
) -> None:
    """Existing QNAP entries keep their identity and no WOL entry is added."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={
            key: value
            for key, value in mock_config_entry.data.items()
            if key != "timeout"
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_form_has_optional_native_wol_help(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Both existing forms expose the stable native assistant link."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["description_placeholders"] == {
        "wake_on_lan_url": WAKE_ON_LAN_CONFIG_FLOW_URL
    }
