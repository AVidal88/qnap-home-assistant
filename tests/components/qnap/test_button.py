"""Tests for QNAP power buttons through Home Assistant's service API."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from qnap_client import (
    QnapAPIError,
    QnapAuthError,
    QnapClient,
    QnapConnectionError,
    QnapPermissionError,
    QnapPowerOutcomeUnknown,
    QnapPowerRejectedError,
)

from homeassistant.const import STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.qnap.const import DOMAIN

from .conftest import TEST_SERIAL


@pytest.fixture
async def power_entities(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> dict[str, str]:
    """Load the integration and find its buttons by stable unique IDs."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entities = {
        action: registry.async_get_entity_id(
            "button", DOMAIN, f"{TEST_SERIAL}_{action}"
        )
        for action in ("shutdown", "reboot")
    }
    assert all(entities.values())
    return entities


@pytest.mark.parametrize("action", ["shutdown", "reboot"])
async def test_press_calls_public_method_once(
    hass: HomeAssistant,
    power_entities: dict[str, str],
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    action: str,
) -> None:
    """A press uses its own client and preserves monitoring and TLS settings."""
    coordinator = mock_config_entry.runtime_data
    info_reads = mock_qnap_client.get_system_info.await_count
    entity = er.async_get(hass).async_get(power_entities[action])
    assert entity is not None
    assert entity.entity_category is EntityCategory.CONFIG
    assert entity.disabled_by is None
    device = dr.async_get(hass).async_get(entity.device_id)
    assert device is not None
    assert (DOMAIN, TEST_SERIAL) in device.identifiers

    control = MagicMock(spec=QnapClient)
    with patch(
        "custom_components.qnap.coordinator.QnapClient", return_value=control
    ) as factory:
        await hass.services.async_call(
            "button", "press", {"entity_id": power_entities[action]}, blocking=True
        )

    factory.assert_called_once_with(
        host=mock_config_entry.data["host"],
        port=mock_config_entry.data["port"],
        username=mock_config_entry.data["username"],
        password=mock_config_entry.data["password"],
        ssl=mock_config_entry.data["ssl"],
        verify_ssl=mock_config_entry.data["verify_ssl"],
        timeout=mock_config_entry.data["timeout"],
    )
    control.login.assert_awaited_once_with()
    getattr(control, action).assert_awaited_once_with()
    getattr(
        control, "reboot" if action == "shutdown" else "shutdown"
    ).assert_not_awaited()
    control.close.assert_awaited_once_with(logout=False)
    control.logout.assert_not_awaited()
    mock_qnap_client.shutdown.assert_not_awaited()
    mock_qnap_client.reboot.assert_not_awaited()
    mock_qnap_client.close.assert_not_awaited()
    assert mock_qnap_client.get_system_info.await_count == info_reads
    assert coordinator.last_update_success


@pytest.mark.parametrize(
    ("error", "translation_key"),
    [
        (QnapAuthError("private-response"), "authentication_failed"),
        (QnapPermissionError("private-response"), "permission_denied"),
        (
            QnapPowerRejectedError("private-response", reason="setting_failed"),
            "power_rejected",
        ),
        (
            QnapPowerOutcomeUnknown("private-response", reason="timeout"),
            "power_outcome_unknown",
        ),
        (QnapConnectionError("private-response"), "power_failed"),
        (QnapAPIError("private-response", http_status=400), "power_failed"),
    ],
)
async def test_action_errors_are_safe_and_do_not_disable_monitoring(
    hass: HomeAssistant,
    power_entities: dict[str, str],
    mock_config_entry: MockConfigEntry,
    error: Exception,
    translation_key: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Rejection and uncertainty are translated independently of sensor access."""
    control = MagicMock(spec=QnapClient)
    control.shutdown.side_effect = error
    with (
        patch("custom_components.qnap.coordinator.QnapClient", return_value=control),
        pytest.raises(HomeAssistantError) as raised,
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": power_entities["shutdown"]}, blocking=True
        )
    assert raised.value.translation_key == translation_key
    assert "private-response" not in str(raised.value)
    assert "private-response" not in caplog.text
    control.shutdown.assert_awaited_once_with()
    control.close.assert_awaited_once_with(logout=False)
    assert mock_config_entry.runtime_data.last_update_success
    assert hass.states.get(power_entities["reboot"]).state != STATE_UNAVAILABLE


async def test_login_failure_does_not_send_power(
    hass: HomeAssistant,
    power_entities: dict[str, str],
) -> None:
    """An unsuccessful login ends the action and closes its local HTTP client."""
    control = MagicMock(spec=QnapClient)
    control.login.side_effect = QnapAuthError("private-response")
    with (
        patch("custom_components.qnap.coordinator.QnapClient", return_value=control),
        pytest.raises(HomeAssistantError) as raised,
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": power_entities["shutdown"]}, blocking=True
        )
    assert raised.value.translation_key == "authentication_failed"
    control.login.assert_awaited_once_with()
    control.shutdown.assert_not_awaited()
    control.reboot.assert_not_awaited()
    control.close.assert_awaited_once_with(logout=False)


async def test_offline_buttons_become_available_after_monitoring_recovers(
    hass: HomeAssistant,
    power_entities: dict[str, str],
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Coordinator availability controls both buttons independently of WOL."""
    coordinator = mock_config_entry.runtime_data
    mock_qnap_client.get_system_info.side_effect = QnapConnectionError("offline")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    for entity_id in power_entities.values():
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    mock_qnap_client.shutdown.assert_not_awaited()
    mock_qnap_client.reboot.assert_not_awaited()

    mock_qnap_client.get_system_info.side_effect = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    for entity_id in power_entities.values():
        assert hass.states.get(entity_id).state != STATE_UNAVAILABLE


async def test_concurrent_press_is_rejected_without_queuing(
    hass: HomeAssistant,
    power_entities: dict[str, str],
    mock_config_entry: MockConfigEntry,
) -> None:
    """Another button press cannot queue a second destructive operation."""
    coordinator = mock_config_entry.runtime_data
    started = asyncio.Event()
    release = asyncio.Event()

    async def wait_for_result() -> None:
        started.set()
        await release.wait()

    control = MagicMock(spec=QnapClient)
    control.shutdown.side_effect = wait_for_result
    with patch(
        "custom_components.qnap.coordinator.QnapClient", return_value=control
    ) as factory:
        first_press = asyncio.create_task(coordinator.async_power_action("shutdown"))
        await started.wait()
        try:
            with pytest.raises(HomeAssistantError) as raised:
                await coordinator.async_power_action("reboot")
            assert raised.value.translation_key == "power_in_progress"
        finally:
            release.set()
            await first_press
    factory.assert_called_once()
    control.shutdown.assert_awaited_once_with()
    control.reboot.assert_not_awaited()


async def test_cleanup_failure_preserves_accepted_request(
    hass: HomeAssistant,
    power_entities: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An acknowledgement remains successful when local cleanup fails."""
    control = MagicMock(spec=QnapClient)
    control.close.side_effect = RuntimeError("private-response")
    with patch("custom_components.qnap.coordinator.QnapClient", return_value=control):
        await hass.services.async_call(
            "button", "press", {"entity_id": power_entities["reboot"]}, blocking=True
        )
    control.reboot.assert_awaited_once_with()
    assert "Unable to close the QNAP power HTTP session" in caplog.text
    assert "private-response" not in caplog.text
