"""Exercise QNAP coordination against the real native Wake on LAN flow."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from qnap_client.models import NetworkInterface

from homeassistant.config_entries import SOURCE_USER, ConfigEntry
from homeassistant.const import CONF_BROADCAST_ADDRESS, CONF_BROADCAST_PORT, CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.qnap.wol import (
    async_ensure_wol,
    find_wol_entity,
    get_mac_candidates,
    normalize_mac,
    resolve_wol_entities,
)

MAC_EXISTING = "02:00:00:00:00:10"
MAC_MISSING = "02:00:00:00:00:20"


@pytest.fixture(autouse=True)
def no_magic_packets():
    """Block the native transmitter while retaining its flow and entities."""
    with patch("wakeonlan.send_magic_packet") as transmitter:
        yield transmitter
        transmitter.assert_not_called()


async def _create_native_entry(hass: HomeAssistant, mac: str) -> ConfigEntry:
    result = await hass.config_entries.flow.async_init(
        "wake_on_lan", context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_MAC: mac,
            CONF_BROADCAST_ADDRESS: "192.0.2.31",
            CONF_BROADCAST_PORT: 9,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return result["result"]


async def test_real_native_flow_creates_entity_and_refuses_duplicate(
    hass: HomeAssistant,
) -> None:
    """The programmatic flow completes with the real native implementation."""
    entry = await _create_native_entry(hass, MAC_EXISTING)
    entity = find_wol_entity(hass, MAC_EXISTING)
    assert entity is not None
    assert entity.config_entry_id == entry.entry_id
    assert hass.states.get(entity.entity_id) is not None

    result = await hass.config_entries.flow.async_init(
        "wake_on_lan", context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MAC: MAC_EXISTING}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert hass.config_entries.async_entries("wake_on_lan") == [entry]
    assert entry.options[CONF_BROADCAST_ADDRESS] == "192.0.2.31"
    assert entry.options[CONF_BROADCAST_PORT] == 9


async def test_existing_is_reused_and_missing_requires_consent(
    hass: HomeAssistant,
) -> None:
    """An explicit match reuses the entry while an unapproved MAC stays absent."""
    entry = await _create_native_entry(hass, MAC_EXISTING)
    original = dict(entry.options)
    existing = await async_ensure_wol(
        hass, MAC_EXISTING, broadcast_address="198.51.100.255", broadcast_port=7
    )
    assert existing.status == "reused"
    assert existing.entry_id == entry.entry_id
    assert existing.entity_registry_id == find_wol_entity(hass, MAC_EXISTING).id
    assert entry.options == original
    missing = await async_ensure_wol(hass, MAC_MISSING)
    assert missing.status == "missing"
    assert len(hass.config_entries.async_entries("wake_on_lan")) == 1


async def test_concurrent_consented_creation_reuses_one_native_entry(
    hass: HomeAssistant,
) -> None:
    """Two consented requests converge on one real native entry and UUID."""
    first, second = await asyncio.gather(
        async_ensure_wol(
            hass,
            MAC_MISSING,
            consent=True,
            broadcast_address="192.0.2.31",
            broadcast_port=9,
        ),
        async_ensure_wol(
            hass,
            MAC_MISSING,
            consent=True,
            broadcast_address="192.0.2.31",
            broadcast_port=9,
        ),
    )
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries("wake_on_lan")
    assert len(entries) == 1
    entity = find_wol_entity(hass, MAC_MISSING)
    assert entity is not None
    assert first.entry_id == second.entry_id == entries[0].entry_id
    assert first.entity_registry_id == second.entity_registry_id == entity.id
    assert {first.status, second.status} <= {"created", "reused"}
    assert er.async_entries_for_config_entry(
        er.async_get(hass), entries[0].entry_id
    ) == [entity]
    assert entries[0].options == {
        CONF_MAC: MAC_MISSING,
        CONF_BROADCAST_ADDRESS: "192.0.2.31",
        CONF_BROADCAST_PORT: 9,
    }


async def test_consent_creates_native_entry_and_locates_real_entity(
    hass: HomeAssistant,
) -> None:
    """Only the consented path submits the native form and returns its UUID."""
    result = await async_ensure_wol(
        hass,
        MAC_MISSING,
        consent=True,
        broadcast_address="192.0.2.31",
        broadcast_port=9,
    )
    await hass.async_block_till_done()
    assert result.status == "created"
    entry = hass.config_entries.async_get_entry(result.entry_id)
    assert entry is not None
    assert entry.domain == "wake_on_lan"
    assert entry.options == {
        CONF_MAC: MAC_MISSING,
        CONF_BROADCAST_ADDRESS: "192.0.2.31",
        CONF_BROADCAST_PORT: 9,
    }
    entity = er.async_get(hass).async_get(result.entity_registry_id)
    assert entity is not None
    assert entity.platform == "wake_on_lan"
    assert hass.states.get(entity.entity_id) is not None


async def test_already_configured_from_real_flow_preserves_existing(
    hass: HomeAssistant,
) -> None:
    """A lookup race reaches native duplicate handling without rewriting options."""
    entry = await _create_native_entry(hass, MAC_EXISTING)
    original = dict(entry.options)
    from custom_components.qnap import wol

    original_lookup = wol._existing_result
    calls = 0

    def first_lookup_misses(hass, mac):
        nonlocal calls
        calls += 1
        return None if calls == 1 else original_lookup(hass, mac)

    with patch(
        "custom_components.qnap.wol._existing_result", side_effect=first_lookup_misses
    ):
        result = await async_ensure_wol(
            hass,
            MAC_EXISTING,
            consent=True,
            broadcast_address="198.51.100.255",
            broadcast_port=7,
        )
    assert result.status == "reused"
    assert result.entry_id == entry.entry_id
    assert entry.options == original
    assert len(hass.config_entries.async_entries("wake_on_lan")) == 1


async def test_renamed_disabled_and_deleted_entities(
    hass: HomeAssistant,
) -> None:
    """Stable registry UUIDs survive renames and preserve owner-disabled state."""
    entry = await _create_native_entry(hass, MAC_EXISTING)
    entity = find_wol_entity(hass, MAC_EXISTING)
    registry = er.async_get(hass)
    registry.async_update_entity(
        entity.entity_id, new_entity_id="button.renamed_nas_wol"
    )
    resolved = resolve_wol_entities(hass, [entity.id])
    assert [item.entity_id for item in resolved] == ["button.renamed_nas_wol"]
    registry.async_update_entity(
        "button.renamed_nas_wol", disabled_by=er.RegistryEntryDisabler.USER
    )
    result = await async_ensure_wol(hass, MAC_EXISTING, consent=True)
    assert result.status == "disabled"
    assert resolve_wol_entities(hass, [entity.id])[0].disabled
    registry.async_remove("button.renamed_nas_wol")
    assert resolve_wol_entities(hass, [entity.id]) == []
    result = await async_ensure_wol(hass, MAC_EXISTING, consent=True)
    assert result.status == "pending"
    assert result.entry_id == entry.entry_id
    assert len(hass.config_entries.async_entries("wake_on_lan")) == 1


async def test_disabled_native_entry_is_not_enabled_or_duplicated(
    hass: HomeAssistant,
) -> None:
    """An owner-disabled entry is reported without setup or implicit changes."""
    from homeassistant.config_entries import ConfigEntryDisabler

    entry = MockConfigEntry(
        domain="wake_on_lan",
        options={CONF_MAC: MAC_EXISTING},
        disabled_by=ConfigEntryDisabler.USER,
    )
    entry.add_to_hass(hass)
    result = await async_ensure_wol(hass, MAC_EXISTING, consent=True)
    assert result.status == "disabled"
    assert result.entry_id == entry.entry_id
    assert entry.disabled_by is ConfigEntryDisabler.USER
    assert len(hass.config_entries.async_entries("wake_on_lan")) == 1


async def test_partial_creation_preserves_success_and_retries_only_missing(
    hass: HomeAssistant,
) -> None:
    """A failed second native form leaves the first entry and its options intact."""
    first = await async_ensure_wol(hass, MAC_EXISTING, consent=True, broadcast_port=9)
    assert first.status == "created"
    failed = await async_ensure_wol(
        hass, MAC_MISSING, consent=True, broadcast_port=99999
    )
    assert failed.status == "error"
    assert failed.reason == "native_flow_failed"
    assert len(hass.config_entries.async_entries("wake_on_lan")) == 1
    assert not hass.config_entries.flow.async_progress_by_handler("wake_on_lan")

    first_again = await async_ensure_wol(
        hass, MAC_EXISTING, consent=True, broadcast_port=7
    )
    assert first_again.status == "reused"
    assert first_again.entity_registry_id == first.entity_registry_id
    assert (
        hass.config_entries.async_get_entry(first.entry_id).options[CONF_BROADCAST_PORT]
        == 9
    )
    second = await async_ensure_wol(hass, MAC_MISSING, consent=True, broadcast_port=9)
    assert second.status == "created"
    assert len(hass.config_entries.async_entries("wake_on_lan")) == 2


async def test_persisted_entry_id_resolves_entity_when_registration_is_ready(
    hass: HomeAssistant,
) -> None:
    """Pending associations can find their entity later through the native entry."""
    entry = await _create_native_entry(hass, MAC_EXISTING)
    entity = find_wol_entity(hass, MAC_EXISTING)
    assert resolve_wol_entities(hass, [], [entry.entry_id]) == [entity]


@pytest.mark.parametrize("mask", ["255.255.255.254", "255.255.255.255"])
def test_point_to_point_or_host_prefix_does_not_suggest_broadcast(mask: str) -> None:
    candidates = get_mac_candidates(
        [NetworkInterface("eth0", MAC_EXISTING, "192.0.2.10", 0, 0, mask=mask)]
    )
    assert candidates == [{"name": "eth0", "mac": MAC_EXISTING}]


def test_candidate_mac_deduplication_and_broadcast() -> None:
    """LACP-shared MACs remain ambiguous and use the actual subnet mask."""
    interfaces = [
        NetworkInterface(
            "eth0", MAC_EXISTING, "192.0.2.10", 0, 0, mask="255.255.255.224"
        ),
        NetworkInterface(
            "bond0", MAC_EXISTING, "192.0.2.10", 0, 0, mask="255.255.255.224"
        ),
        NetworkInterface("unknown", "", "", 0, 0),
        NetworkInterface("eth1", MAC_MISSING, "198.51.100.10", 0, 0, mask="bad-mask"),
    ]
    assert get_mac_candidates(interfaces) == [
        {"name": "eth0, bond0", "mac": MAC_EXISTING, "broadcast_address": "192.0.2.31"},
        {"name": "eth1", "mac": MAC_MISSING},
    ]


@pytest.mark.parametrize(
    "value",
    ["", "invalid", "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "01:00:00:00:00:01"],
)
def test_invalid_or_group_mac_is_not_a_candidate(value: str) -> None:
    assert normalize_mac(value) is None
