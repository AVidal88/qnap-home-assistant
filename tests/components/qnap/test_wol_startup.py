"""Native WOL delegation and QNAP cold-start recovery without NAS access."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import MagicMock, call, patch

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from qnap_client import QnapAuthError, QnapConnectionError

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import (
    CONF_BROADCAST_ADDRESS,
    CONF_BROADCAST_PORT,
    CONF_MAC,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.qnap.const import CONF_WOL_ENTITIES, CONF_WOL_ENTRY_IDS, DOMAIN

from .conftest import TEST_SERIAL

MAC = "02:00:00:00:00:01"


async def create_native_wol(hass: HomeAssistant, mac: str = MAC):
    """Create and load the actual built-in WOL integration through its flow."""
    result = await hass.config_entries.flow.async_init(
        "wake_on_lan", context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_MAC: mac}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("button", "wake_on_lan", mac)
    assert entity_id is not None
    return result["result"], registry.async_get(entity_id)


async def setup_qnap(
    hass: HomeAssistant, entry: MockConfigEntry, native_entry, native_entity
) -> dict[str, str]:
    """Associate a QNAP entry with the real native entity and load QNAP."""
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_WOL_ENTITIES: [native_entity.id],
            CONF_WOL_ENTRY_IDS: [native_entry.entry_id],
        },
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entities = {
        action: registry.async_get_entity_id(
            "button", DOMAIN, f"{TEST_SERIAL}_{action}"
        )
        for action in ("wake", "shutdown", "reboot")
    }
    assert all(entities.values())
    return entities


async def test_cold_start_offline_loads_native_wol_and_proxy(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Persisted associations load wake controls before QTS can be reached."""
    with patch("wakeonlan.send_magic_packet") as send_packet:
        native_entry, native_entity = await create_native_wol(hass)
        assert await hass.config_entries.async_unload(native_entry.entry_id)
        assert native_entry.state is ConfigEntryState.NOT_LOADED
        mock_qnap_client.login.side_effect = QnapConnectionError("offline")
        mock_qnap_client.get_system_info.side_effect = QnapConnectionError("offline")
        buttons = await setup_qnap(hass, mock_config_entry, native_entry, native_entity)

        assert mock_config_entry.state is ConfigEntryState.LOADED
        assert native_entry.state is ConfigEntryState.LOADED
        assert not mock_config_entry.runtime_data.last_update_success
        assert all(
            not entity_id.startswith("button.none_") for entity_id in buttons.values()
        )
        wake_registry_entry = er.async_get(hass).async_get(buttons["wake"])
        device = dr.async_get(hass).async_get(wake_registry_entry.device_id)
        assert device is not None
        assert device.name == mock_config_entry.title
        assert hass.states.get(buttons["wake"]).state != STATE_UNAVAILABLE
        assert hass.states.get(buttons["shutdown"]).state == STATE_UNAVAILABLE
        assert hass.states.get(buttons["reboot"]).state == STATE_UNAVAILABLE
        send_packet.assert_not_called()

        await hass.services.async_call(
            "button", "press", {"entity_id": buttons["wake"]}, blocking=True
        )
        send_packet.assert_called_once_with(MAC)
        mock_qnap_client.shutdown.assert_not_awaited()
        mock_qnap_client.reboot.assert_not_awaited()

        mock_qnap_client.login.side_effect = None
        mock_qnap_client.get_system_info.side_effect = [
            QnapAuthError("No monitoring session after offline startup"),
            mock_qnap_client.get_system_info.return_value,
        ]
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
        await hass.async_block_till_done()
        assert mock_qnap_client.login.await_count == 2
        assert mock_config_entry.runtime_data.last_update_success
        assert hass.states.get("sensor.test_nas_cpu_usage") is not None
        assert hass.states.get(buttons["shutdown"]).state != STATE_UNAVAILABLE
        assert hass.states.get(buttons["reboot"]).state != STATE_UNAVAILABLE
        send_packet.assert_called_once_with(MAC)


async def test_qnap_can_initialize_wol_component_first_while_nas_is_offline(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Persisted native entries load even when WOL's component has not started."""
    native_entry = MockConfigEntry(
        domain="wake_on_lan", title="NAS wake", data={}, options={CONF_MAC: MAC}
    )
    native_entry.add_to_hass(hass)
    native_entity = er.async_get(hass).async_get_or_create(
        "button", "wake_on_lan", MAC, config_entry=native_entry
    )
    assert "wake_on_lan" not in hass.config.components
    mock_qnap_client.login.side_effect = QnapConnectionError("offline")
    with patch("wakeonlan.send_magic_packet") as send_packet:
        buttons = await setup_qnap(hass, mock_config_entry, native_entry, native_entity)
        assert "wake_on_lan" in hass.config.components
        assert native_entry.state is ConfigEntryState.LOADED
        assert hass.states.get(buttons["wake"]).state != STATE_UNAVAILABLE
        assert hass.states.get(buttons["shutdown"]).state == STATE_UNAVAILABLE
        send_packet.assert_not_called()
        await hass.services.async_call(
            "button", "press", {"entity_id": buttons["wake"]}, blocking=True
        )
        send_packet.assert_called_once_with(MAC)


async def test_proxy_tracks_renamed_disabled_and_deleted_native_entity(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Stable registry associations survive rename and respect user disable/delete."""
    with patch("wakeonlan.send_magic_packet") as send_packet:
        native_entry, native_entity = await create_native_wol(hass)
        buttons = await setup_qnap(hass, mock_config_entry, native_entry, native_entity)
        registry = er.async_get(hass)
        registry.async_update_entity(
            native_entity.entity_id, new_entity_id="button.nas_native_wake"
        )
        await hass.async_block_till_done()
        await hass.services.async_call(
            "button", "press", {"entity_id": buttons["wake"]}, blocking=True
        )
        send_packet.assert_called_once_with(MAC)
        registry.async_update_entity(
            "button.nas_native_wake", disabled_by=er.RegistryEntryDisabler.USER
        )
        await hass.async_block_till_done()
        assert hass.states.get(buttons["wake"]).state == STATE_UNAVAILABLE
        assert (
            registry.async_get("button.nas_native_wake").disabled_by
            is er.RegistryEntryDisabler.USER
        )
        send_packet.assert_called_once_with(MAC)
        registry.async_remove("button.nas_native_wake")
        await hass.async_block_till_done()
        assert hass.states.get(buttons["wake"]).state == STATE_UNAVAILABLE
        assert len(hass.config_entries.async_entries("wake_on_lan")) == 1
        assert registry.async_get("button.nas_native_wake") is None
        send_packet.assert_called_once_with(MAC)


async def test_disabled_native_entry_is_not_enabled_on_offline_startup(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """QNAP never changes the owner's disabled integration selection."""
    from homeassistant.config_entries import ConfigEntryDisabler

    with patch("wakeonlan.send_magic_packet") as send_packet:
        native_entry, native_entity = await create_native_wol(hass)
        assert await hass.config_entries.async_unload(native_entry.entry_id)
        await hass.config_entries.async_set_disabled_by(
            native_entry.entry_id, ConfigEntryDisabler.USER
        )
        mock_qnap_client.login.side_effect = QnapConnectionError("offline")
        buttons = await setup_qnap(hass, mock_config_entry, native_entry, native_entity)
        assert native_entry.disabled_by is ConfigEntryDisabler.USER
        assert hass.states.get(buttons["wake"]).state == STATE_UNAVAILABLE
        send_packet.assert_not_called()


async def test_omitting_associations_makes_proxy_unavailable(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reversible opt-out changes only the QNAP association."""
    with patch("wakeonlan.send_magic_packet") as send_packet:
        native_entry, native_entity = await create_native_wol(hass)
        buttons = await setup_qnap(hass, mock_config_entry, native_entry, native_entity)
        hass.config_entries.async_update_entry(
            mock_config_entry, options={CONF_WOL_ENTITIES: [], CONF_WOL_ENTRY_IDS: []}
        )
        await hass.async_block_till_done()
        assert hass.states.get(buttons["wake"]).state == STATE_UNAVAILABLE
        assert native_entry.state is ConfigEntryState.LOADED
        hass.config_entries.async_update_entry(
            mock_config_entry,
            options={
                CONF_WOL_ENTITIES: [native_entity.id],
                CONF_WOL_ENTRY_IDS: [native_entry.entry_id],
            },
        )
        await hass.async_block_till_done()
        assert hass.states.get(buttons["wake"]).state != STATE_UNAVAILABLE
        send_packet.assert_not_called()


async def test_removed_native_entry_is_not_recreated_when_qnap_reloads_offline(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A removed native entry remains removed until the owner consents again."""
    with patch("wakeonlan.send_magic_packet") as send_packet:
        native_entry, native_entity = await create_native_wol(hass)
        buttons = await setup_qnap(hass, mock_config_entry, native_entry, native_entity)
        await hass.config_entries.async_remove(native_entry.entry_id)
        await hass.async_block_till_done()
        mock_qnap_client.login.side_effect = QnapConnectionError("offline")
        assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert not hass.config_entries.async_entries("wake_on_lan")
        assert er.async_get(hass).async_get(native_entity.id) is None
        assert hass.states.get(buttons["wake"]).state == STATE_UNAVAILABLE
        send_packet.assert_not_called()


async def test_wol_setup_in_progress_finishes_without_a_second_setup(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """QNAP tolerates an earlier concurrent native WOL setup at HA startup."""
    import homeassistant.components.wake_on_lan as native_wol

    with patch("wakeonlan.send_magic_packet") as send_packet:
        native_entry, native_entity = await create_native_wol(hass)
        assert await hass.config_entries.async_unload(native_entry.entry_id)
        mock_config_entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(
            mock_config_entry,
            options={
                CONF_WOL_ENTITIES: [native_entity.id],
                CONF_WOL_ENTRY_IDS: [native_entry.entry_id],
            },
        )
        mock_qnap_client.login.side_effect = QnapConnectionError("offline")
        started = asyncio.Event()
        release = asyncio.Event()
        original_setup = native_wol.async_setup_entry

        async def controlled_setup(hass, entry):
            started.set()
            await release.wait()
            return await original_setup(hass, entry)

        with patch.object(
            native_wol, "async_setup_entry", side_effect=controlled_setup
        ) as setup:
            native_setup = asyncio.create_task(
                hass.config_entries.async_setup(native_entry.entry_id)
            )
            await started.wait()
            try:
                assert native_entry.state is ConfigEntryState.SETUP_IN_PROGRESS
                assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            finally:
                release.set()
                assert await native_setup
            await hass.async_block_till_done()
            setup.assert_awaited_once()
        wake_id = er.async_get(hass).async_get_entity_id(
            "button", DOMAIN, f"{TEST_SERIAL}_wake"
        )
        assert hass.states.get(wake_id).state != STATE_UNAVAILABLE
        send_packet.assert_not_called()


async def test_proxy_delegates_once_to_each_selected_native_button(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Several physical interfaces use native actions without duplicate sends."""
    second_mac = "02:00:00:00:00:02"
    with patch("wakeonlan.send_magic_packet") as send_packet:
        first_entry, first_entity = await create_native_wol(hass)
        second_entry, second_entity = await create_native_wol(hass, second_mac)
        buttons = await setup_qnap(hass, mock_config_entry, first_entry, first_entity)
        hass.config_entries.async_update_entry(
            mock_config_entry,
            options={
                CONF_WOL_ENTITIES: [first_entity.id, second_entity.id, first_entity.id],
                CONF_WOL_ENTRY_IDS: [first_entry.entry_id, second_entry.entry_id],
            },
        )
        await hass.async_block_till_done()
        send_packet.assert_not_called()
        await hass.services.async_call(
            "button", "press", {"entity_id": buttons["wake"]}, blocking=True
        )
        send_packet.assert_has_calls([call(MAC), call(second_mac)], any_order=True)
        assert send_packet.call_count == 2


async def test_existing_sensors_keep_identity_across_offline_reload_and_recovery(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An offline restart preserves sensor registration until data recovers."""
    with patch("wakeonlan.send_magic_packet") as send_packet:
        native_entry, native_entity = await create_native_wol(hass)
        buttons = await setup_qnap(hass, mock_config_entry, native_entry, native_entity)
        registry = er.async_get(hass)
        cpu_entity_id = "sensor.test_nas_cpu_usage"
        cpu_registry_id = registry.async_get(cpu_entity_id).id
        registered = {
            entity.id
            for entity in er.async_entries_for_config_entry(
                registry, mock_config_entry.entry_id
            )
            if entity.domain == "sensor"
        }
        assert hass.states.get(cpu_entity_id).state != STATE_UNAVAILABLE
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        mock_qnap_client.login.side_effect = QnapConnectionError("offline")
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert registry.async_get(cpu_entity_id).id == cpu_registry_id
        assert hass.states.get(cpu_entity_id).state == STATE_UNAVAILABLE
        assert hass.states.get(buttons["shutdown"]).state == STATE_UNAVAILABLE
        assert hass.states.get(buttons["reboot"]).state == STATE_UNAVAILABLE
        assert hass.states.get(buttons["wake"]).state != STATE_UNAVAILABLE

        mock_qnap_client.login.side_effect = None
        mock_qnap_client.get_system_info.side_effect = [
            QnapAuthError("No monitoring session after offline startup"),
            mock_qnap_client.get_system_info.return_value,
        ]
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
        await hass.async_block_till_done()
        assert hass.states.get(cpu_entity_id).state != STATE_UNAVAILABLE
        assert registry.async_get(cpu_entity_id).id == cpu_registry_id
        assert {
            entity.id
            for entity in er.async_entries_for_config_entry(
                registry, mock_config_entry.entry_id
            )
            if entity.domain == "sensor"
        } == registered
        send_packet.assert_not_called()


async def test_options_association_loads_offline_qnap_without_waiting_for_retry(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Associating WOL in Options promptly recovers QNAP from setup retry."""
    with patch("wakeonlan.send_magic_packet") as send_packet:
        mock_config_entry.add_to_hass(hass)
        mock_qnap_client.login.side_effect = QnapConnectionError("offline")
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
        native_entry, native_entity = await create_native_wol(hass)
        original_options = dict(native_entry.options)
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_WOL_ENTITIES: [native_entity.entity_id]}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        wake = registry.async_get_entity_id("button", DOMAIN, f"{TEST_SERIAL}_wake")
        shutdown = registry.async_get_entity_id(
            "button", DOMAIN, f"{TEST_SERIAL}_shutdown"
        )
        reboot = registry.async_get_entity_id("button", DOMAIN, f"{TEST_SERIAL}_reboot")
        assert mock_config_entry.state is ConfigEntryState.LOADED
        assert hass.states.get(wake).state != STATE_UNAVAILABLE
        assert hass.states.get(shutdown).state == STATE_UNAVAILABLE
        assert hass.states.get(reboot).state == STATE_UNAVAILABLE
        assert len(hass.config_entries.async_entries("wake_on_lan")) == 1
        assert dict(native_entry.options) == original_options
        send_packet.assert_not_called()


async def test_proxy_uses_settings_changed_through_native_wol_options(
    hass: HomeAssistant,
    mock_qnap_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The native integration retains ownership of broadcast and port choices."""
    with patch("wakeonlan.send_magic_packet") as send_packet:
        native_entry, native_entity = await create_native_wol(hass)
        buttons = await setup_qnap(hass, mock_config_entry, native_entry, native_entity)
        qnap_options = dict(mock_config_entry.options)
        result = await hass.config_entries.options.async_init(native_entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_BROADCAST_ADDRESS: "192.0.2.63", CONF_BROADCAST_PORT: 7},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        await hass.services.async_call(
            "button", "press", {"entity_id": buttons["wake"]}, blocking=True
        )
        send_packet.assert_called_once_with(MAC, ip_address="192.0.2.63", port=7)
        assert dict(mock_config_entry.options) == qnap_options
        assert CONF_BROADCAST_ADDRESS not in mock_config_entry.options
        assert CONF_BROADCAST_PORT not in mock_config_entry.options
