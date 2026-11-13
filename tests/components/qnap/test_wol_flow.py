"""Exercise the assisted QNAP UI with the real native WOL config flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from qnap_client import QnapAPIError, QnapPermissionError
from qnap_client.models import NetworkInterface

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import (
    CONF_BROADCAST_ADDRESS,
    CONF_BROADCAST_PORT,
    CONF_MAC,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.qnap.const import (
    CONF_WOL_CANDIDATES,
    CONF_WOL_ENTITIES,
    CONF_WOL_ENTRY_IDS,
    CONF_WOL_MACS,
    CONF_WOL_SUGGESTIONS_DISMISSED,
    DOMAIN,
)
from custom_components.qnap.wol import WolResult, find_wol_entity

from .conftest import TEST_SERIAL

MAC_EXISTING = "02:00:00:00:00:10"
MAC_MISSING = "02:00:00:00:00:20"
MAC_THIRD = "02:00:00:00:00:30"


@pytest.fixture(autouse=True)
def no_magic_packets():
    """Retain real native flows and buttons while preventing any transmission."""
    with patch("wakeonlan.send_magic_packet") as transmitter:
        yield transmitter
        transmitter.assert_not_called()


async def _create_native_entry(hass: HomeAssistant, mac: str):
    result = await hass.config_entries.flow.async_init(
        "wake_on_lan", context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MAC: mac, CONF_BROADCAST_ADDRESS: "192.0.2.31", CONF_BROADCAST_PORT: 9},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return result["result"]


async def _start_qnap(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            key: value
            for key, value in mock_config_entry.data.items()
            if key != "timeout"
        },
    )


async def _finish_summary(hass: HomeAssistant, result):
    assert result["step_id"] == "wol_summary"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return result


async def test_assisted_setup_reuses_creates_and_persists_associations(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    qnap_connect: MagicMock,
    mock_setup_entry: MagicMock,
) -> None:
    """Simulated QTS MACs drive real WOL creation after explicit UI consent."""
    existing_entry = await _create_native_entry(hass, MAC_EXISTING)
    original_options = dict(existing_entry.options)
    qnap_connect.get_network_interfaces.return_value = [
        NetworkInterface(
            "eth0", MAC_EXISTING, "192.0.2.10", 0, 0, mask="255.255.255.224"
        ),
        NetworkInterface(
            "bond0", MAC_EXISTING, "192.0.2.10", 0, 0, mask="255.255.255.224"
        ),
        NetworkInterface(
            "eth1", MAC_MISSING, "192.0.2.11", 0, 0, mask="255.255.255.224"
        ),
    ]
    result = await _start_qnap(hass, mock_config_entry)
    assert result["step_id"] == "wol"
    qnap_connect.get_network_interfaces.assert_awaited_once_with()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_WOL_MACS: [MAC_EXISTING, MAC_MISSING],
            "create_missing": True,
            CONF_WOL_SUGGESTIONS_DISMISSED: True,
        },
    )
    assert result["step_id"] == "wol_create"
    assert result["description_placeholders"]["mac"] == MAC_MISSING
    assert len(hass.config_entries.async_entries("wake_on_lan")) == 1

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "confirm_create": True,
            "broadcast_address": "192.0.2.31",
            "broadcast_port": 9,
        },
    )
    assert result["description_placeholders"]["created"] == "1"
    assert result["description_placeholders"]["reused"] == "1"
    result = await _finish_summary(hass, result)
    qnap_entry = result["result"]
    native_entities = [
        find_wol_entity(hass, mac) for mac in (MAC_EXISTING, MAC_MISSING)
    ]
    assert set(qnap_entry.options[CONF_WOL_ENTITIES]) == {
        entity.id for entity in native_entities
    }
    assert set(qnap_entry.options[CONF_WOL_ENTRY_IDS]) == {
        entity.config_entry_id for entity in native_entities
    }
    assert qnap_entry.options[CONF_WOL_SUGGESTIONS_DISMISSED] is True
    assert qnap_entry.options[CONF_WOL_MACS] == [MAC_EXISTING, MAC_MISSING]
    assert existing_entry.options == original_options
    assert len(hass.config_entries.async_entries("wake_on_lan")) == 2
    assert [
        candidate["name"] for candidate in qnap_entry.options[CONF_WOL_CANDIDATES]
    ] == ["eth0, bond0", "eth1"]
    assert all(
        "broadcast_address" not in candidate
        for candidate in qnap_entry.options[CONF_WOL_CANDIDATES]
    )


async def test_creation_requires_its_explicit_confirmation(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    qnap_connect: MagicMock,
    mock_setup_entry: MagicMock,
) -> None:
    """Selecting the creation workflow does not authorize its per-MAC request."""
    qnap_connect.get_network_interfaces.return_value = [
        NetworkInterface("eth0", MAC_MISSING, "", 0, 0),
    ]
    result = await _start_qnap(hass, mock_config_entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_WOL_MACS: [MAC_MISSING], "create_missing": True},
    )
    assert result["step_id"] == "wol_create"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["description_placeholders"]["unconfigured"] == "1"
    result = await _finish_summary(hass, result)
    assert result["result"].options[CONF_WOL_ENTITIES] == []
    assert not hass.config_entries.async_entries("wake_on_lan")


async def test_options_are_accessible_offline_and_dismissal_is_reversible(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    qnap_connect: MagicMock,
) -> None:
    """A saved NAS entry can associate a manual physical MAC without QTS I/O."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_WOL_SUGGESTIONS_DISMISSED: True}
    )
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["step_id"] == "wol"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "manual_macs": MAC_MISSING,
            "create_missing": True,
            CONF_WOL_SUGGESTIONS_DISMISSED: False,
        },
    )
    assert result["step_id"] == "wol_create"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"confirm_create": True, "broadcast_port": 9}
    )
    assert result["step_id"] == "wol_summary"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_WOL_SUGGESTIONS_DISMISSED] is False
    assert mock_config_entry.options[CONF_WOL_MACS] == [MAC_MISSING]
    assert mock_config_entry.options[CONF_WOL_ENTITIES] == [
        find_wol_entity(hass, MAC_MISSING).id
    ]
    qnap_connect.__aenter__.assert_not_awaited()
    qnap_connect.get_network_interfaces.assert_not_awaited()


async def test_options_preserve_partial_real_creation_before_later_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """First real native creation stays associated when the next request fails."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"manual_macs": f"{MAC_MISSING}, {MAC_THIRD}", "create_missing": True},
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"confirm_create": True, "broadcast_port": 9}
    )
    assert result["step_id"] == "wol_create"
    first_entity = find_wol_entity(hass, MAC_MISSING)
    assert first_entity.id in mock_config_entry.options[CONF_WOL_ENTITIES]
    assert first_entity.config_entry_id in mock_config_entry.options[CONF_WOL_ENTRY_IDS]
    assert len(hass.config_entries.async_entries("wake_on_lan")) == 1

    from custom_components.qnap import wol_flow

    real_ensure = wol_flow.async_ensure_wol

    async def reject_second(hass, mac, **kwargs):
        if mac == MAC_THIRD and kwargs.get("consent"):
            return WolResult(status="error", mac=mac, reason="native_flow_failed")
        return await real_ensure(hass, mac, **kwargs)

    with patch(
        "custom_components.qnap.wol_flow.async_ensure_wol", side_effect=reject_second
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"confirm_create": True, "broadcast_port": 9}
        )
    assert result["errors"] == {"base": "wol_creation_failed"}
    assert mock_config_entry.options[CONF_WOL_ENTITIES] == [first_entity.id]
    assert len(hass.config_entries.async_entries("wake_on_lan")) == 1
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"confirm_create": False}
    )
    assert result["description_placeholders"]["created"] == "1"
    assert result["description_placeholders"]["unconfigured"] == "1"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_WOL_ENTITIES] == [first_entity.id]


async def test_manual_entity_selection_survives_rename_and_preserves_disabled_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The owner can select a native entity with stable persistence and no enable."""
    await _create_native_entry(hass, MAC_EXISTING)
    entity = find_wol_entity(hass, MAC_EXISTING)
    registry = er.async_get(hass)
    registry.async_update_entity(
        entity.entity_id, new_entity_id="button.selected_nas_wol"
    )
    registry.async_update_entity(
        "button.selected_nas_wol", disabled_by=er.RegistryEntryDisabler.USER
    )
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WOL_ENTITIES: ["button.selected_nas_wol"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_WOL_ENTITIES] == [entity.id]
    assert registry.async_get(entity.id).disabled_by is er.RegistryEntryDisabler.USER
    assert len(hass.config_entries.async_entries("wake_on_lan")) == 1


async def test_invalid_manual_mac_preserves_form_without_native_creation(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"manual_macs": "not-a-mac", "create_missing": True}
    )
    assert result["step_id"] == "wol"
    assert result["errors"] == {"manual_macs": "invalid_mac"}
    assert not hass.config_entries.async_entries("wake_on_lan")


async def test_dismissed_suggestions_skip_reconfigure_until_options_reenable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    qnap_connect: MagicMock,
    mock_setup_entry: MagicMock,
) -> None:
    """The per-NAS omission persists while Options remains an explicit entry point."""
    qnap_connect.get_network_interfaces.return_value = [
        NetworkInterface("eth0", MAC_MISSING, "", 0, 0)
    ]
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_WOL_SUGGESTIONS_DISMISSED: True}
    )
    connection = {
        key: value for key, value in mock_config_entry.data.items() if key != "timeout"
    }
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
        data=connection,
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.options[CONF_WOL_SUGGESTIONS_DISMISSED] is True
    assert not hass.config_entries.async_entries("wake_on_lan")

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["step_id"] == "wol"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WOL_SUGGESTIONS_DISMISSED: False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_WOL_SUGGESTIONS_DISMISSED] is False

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_RECONFIGURE,
            "entry_id": mock_config_entry.entry_id,
        },
        data=connection,
    )
    assert result["step_id"] == "wol"
    assert qnap_connect.get_network_interfaces.await_count == 2
    hass.config_entries.flow.async_abort(result["flow_id"])


async def test_suggestion_preference_is_scoped_to_its_nas(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Saving one NAS preference leaves another QNAP entry's choice intact."""
    mock_config_entry.add_to_hass(hass)
    other = MockConfigEntry(
        domain=DOMAIN,
        unique_id="OTHER-NAS",
        title="Other NAS",
        data={**mock_config_entry.data, "host": "192.0.2.20"},
    )
    other.add_to_hass(hass)
    for entry, dismissed in ((mock_config_entry, True), (other, False)):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_WOL_SUGGESTIONS_DISMISSED: dismissed}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_WOL_SUGGESTIONS_DISMISSED] is True
    assert other.options[CONF_WOL_SUGGESTIONS_DISMISSED] is False
    assert not hass.config_entries.async_entries("wake_on_lan")


@pytest.mark.parametrize(
    "error",
    [QnapPermissionError("private-response"), QnapAPIError("private-response")],
)
async def test_optional_mac_discovery_failure_preserves_qnap_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    qnap_connect: MagicMock,
    mock_setup_entry: MagicMock,
    error: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unavailable network metadata leaves monitoring setup and manual WOL usable."""
    qnap_connect.get_network_interfaces.side_effect = error
    result = await _start_qnap(hass, mock_config_entry)
    assert result["step_id"] == "wol"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].options[CONF_WOL_CANDIDATES] == []
    assert "private-response" not in caplog.text
    assert not hass.config_entries.async_entries("wake_on_lan")


@pytest.mark.parametrize("initial_payload", [False, True])
async def test_omitted_options_preserve_saved_mac_association_and_preference(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    initial_payload: bool,
) -> None:
    """Both public options entry points preserve saved fields omitted by input."""
    native_entry = await _create_native_entry(hass, MAC_EXISTING)
    entity = find_wol_entity(hass, MAC_EXISTING)
    native_options = dict(native_entry.options)
    mock_config_entry.add_to_hass(hass)
    saved = {
        CONF_WOL_MACS: [MAC_EXISTING],
        CONF_WOL_ENTITIES: [entity.id],
        CONF_WOL_ENTRY_IDS: [native_entry.entry_id],
        CONF_WOL_SUGGESTIONS_DISMISSED: True,
    }
    hass.config_entries.async_update_entry(mock_config_entry, options=saved)
    if initial_payload:
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id, data={}
        )
    else:
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {}
        )
    assert result["step_id"] == "wol_summary"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    for key, value in saved.items():
        assert mock_config_entry.options[key] == value
    assert native_entry.options == native_options
    assert hass.config_entries.async_entries("wake_on_lan") == [native_entry]


async def test_preference_edit_preserves_stale_binding_after_native_entry_removed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_qnap_client: MagicMock,
) -> None:
    """A preference-only edit preserves a missing target without recreating it."""
    native_entry = await _create_native_entry(hass, MAC_EXISTING)
    entity = find_wol_entity(hass, MAC_EXISTING)
    mock_config_entry.add_to_hass(hass)
    saved = {
        CONF_WOL_MACS: [MAC_EXISTING],
        CONF_WOL_ENTITIES: [entity.id],
        CONF_WOL_ENTRY_IDS: [native_entry.entry_id],
        CONF_WOL_SUGGESTIONS_DISMISSED: False,
    }
    hass.config_entries.async_update_entry(mock_config_entry, options=saved)
    await hass.config_entries.async_remove(native_entry.entry_id)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    wake_entity_id = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, f"{TEST_SERIAL}_wake"
    )
    assert hass.states.get(wake_entity_id).state == STATE_UNAVAILABLE

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WOL_SUGGESTIONS_DISMISSED: True}
    )
    assert result["step_id"] == "wol_summary"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_WOL_ENTITIES] == [entity.id]
    assert mock_config_entry.options[CONF_WOL_ENTRY_IDS] == [native_entry.entry_id]
    assert mock_config_entry.options[CONF_WOL_MACS] == [MAC_EXISTING]
    assert mock_config_entry.options[CONF_WOL_SUGGESTIONS_DISMISSED] is True
    assert hass.states.get(wake_entity_id).state == STATE_UNAVAILABLE
    assert not hass.config_entries.async_entries("wake_on_lan")


async def test_explicit_clear_detaches_only_qnap_association(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Clearing both target inputs preserves the native entry and saved omission."""
    native_entry = await _create_native_entry(hass, MAC_EXISTING)
    entity = find_wol_entity(hass, MAC_EXISTING)
    native_options = dict(native_entry.options)
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            CONF_WOL_MACS: [MAC_EXISTING],
            CONF_WOL_ENTITIES: [entity.id],
            CONF_WOL_ENTRY_IDS: [native_entry.entry_id],
            CONF_WOL_SUGGESTIONS_DISMISSED: True,
        },
    )
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WOL_MACS: [], CONF_WOL_ENTITIES: []}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_WOL_MACS] == []
    assert mock_config_entry.options[CONF_WOL_ENTITIES] == []
    assert mock_config_entry.options[CONF_WOL_ENTRY_IDS] == []
    assert mock_config_entry.options[CONF_WOL_SUGGESTIONS_DISMISSED] is True
    assert native_entry.options == native_options
    assert hass.config_entries.async_entries("wake_on_lan") == [native_entry]
    assert er.async_get(hass).async_get(entity.id) is not None
