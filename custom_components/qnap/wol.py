"""Associate QNAP interfaces with Home Assistant's native WOL buttons."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from ipaddress import IPv4Interface
import re
from typing import Literal

from qnap_client.models import NetworkInterface

from homeassistant.config_entries import SOURCE_USER, ConfigEntry
from homeassistant.const import CONF_BROADCAST_ADDRESS, CONF_BROADCAST_PORT, CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

WOL_DOMAIN = "wake_on_lan"


@dataclass(frozen=True, kw_only=True)
class WolResult:
    """Describe one association attempt without storing WOL network settings."""

    status: Literal["created", "reused", "pending", "disabled", "missing", "error"]
    mac: str
    entity_registry_id: str | None = None
    entry_id: str | None = None
    reason: str | None = None


def normalize_mac(value: str) -> str | None:
    """Validate a usable unicast MAC while accepting HA's supported formats."""
    if not isinstance(value, str):
        return None
    normalized = dr.format_mac(value.strip())
    if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", normalized):
        return None
    if normalized == "00:00:00:00:00:00" or int(normalized[:2], 16) & 1:
        return None
    return normalized


def get_mac_candidates(interfaces: Iterable[NetworkInterface]) -> list[dict[str, str]]:
    """Return deduplicated candidates requiring physical-interface confirmation."""
    candidates: dict[str, dict[str, str]] = {}
    for interface in interfaces:
        if (mac := normalize_mac(interface.mac)) is None:
            continue
        if mac in candidates:
            candidates[mac]["name"] += f", {interface.name}"
            continue
        candidate = candidates[mac] = {"name": interface.name, "mac": mac}
        if interface.ip and interface.mask:
            try:
                network = IPv4Interface(f"{interface.ip}/{interface.mask}").network
                if network.prefixlen < 31:
                    candidate["broadcast_address"] = str(network.broadcast_address)
            except ValueError:
                pass
    return list(candidates.values())


def _is_native_button(hass: HomeAssistant, entity: er.RegistryEntry) -> bool:
    """Verify platform and owning config entry before using a registry match."""
    entry = hass.config_entries.async_get_entry(entity.config_entry_id)
    return (
        entity.domain == "button"
        and entity.platform == WOL_DOMAIN
        and entry is not None
        and entry.domain == WOL_DOMAIN
    )


def find_wol_entity(hass: HomeAssistant, mac: str) -> er.RegistryEntry | None:
    """Find an existing native button by its canonical MAC unique ID."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("button", WOL_DOMAIN, mac)
    if entity_id is None:
        return None
    entity = registry.async_get(entity_id)
    if entity is not None and _is_native_button(hass, entity):
        return entity
    return None


def resolve_wol_entities(
    hass: HomeAssistant,
    registry_ids: Iterable[str],
    entry_ids: Iterable[str] = (),
) -> list[er.RegistryEntry]:
    """Resolve stable associations, including renamed and disabled entities."""
    registry = er.async_get(hass)
    entities: dict[str, er.RegistryEntry] = {}
    for registry_id in registry_ids:
        if (
            entity := registry.async_get(registry_id)
        ) is not None and _is_native_button(hass, entity):
            entities[entity.id] = entity
    for entry_id in entry_ids:
        for entity in er.async_entries_for_config_entry(registry, entry_id):
            if _is_native_button(hass, entity):
                entities[entity.id] = entity
    return list(entities.values())


def _find_native_entry(hass: HomeAssistant, mac: str) -> ConfigEntry | None:
    """Identify an unloaded or disabled entry without changing it."""
    for entry in hass.config_entries.async_entries(WOL_DOMAIN):
        if normalize_mac(entry.options.get(CONF_MAC, "")) == mac:
            return entry
    return None


def _existing_result(hass: HomeAssistant, mac: str) -> WolResult | None:
    """Describe an existing association without loading or enabling it."""
    if (entity := find_wol_entity(hass, mac)) is not None:
        entry = hass.config_entries.async_get_entry(entity.config_entry_id)
        return WolResult(
            status="disabled" if entity.disabled or entry.disabled_by else "reused",
            mac=mac,
            entity_registry_id=entity.id,
            entry_id=entity.config_entry_id,
        )
    if (entry := _find_native_entry(hass, mac)) is not None:
        return WolResult(
            status="disabled" if entry.disabled_by else "pending",
            mac=mac,
            entry_id=entry.entry_id,
        )
    return None


async def async_ensure_wol(
    hass: HomeAssistant,
    mac: str,
    *,
    consent: bool = False,
    broadcast_address: str | None = None,
    broadcast_port: int | None = None,
) -> WolResult:
    """Reuse an existing button or submit the real native flow after consent."""
    if (normalized := normalize_mac(mac)) is None:
        return WolResult(status="error", mac=mac, reason="invalid_mac")
    if (existing := _existing_result(hass, normalized)) is not None:
        return existing
    if not consent:
        return WolResult(status="missing", mac=normalized)

    data: dict[str, str | int] = {CONF_MAC: normalized}
    if broadcast_address is not None:
        data[CONF_BROADCAST_ADDRESS] = broadcast_address
    if broadcast_port is not None:
        data[CONF_BROADCAST_PORT] = broadcast_port

    flow_id: str | None = None
    try:
        result = await hass.config_entries.flow.async_init(
            WOL_DOMAIN, context={"source": SOURCE_USER}
        )
        if result["type"] is FlowResultType.FORM and result["step_id"] == "user":
            flow_id = result["flow_id"]
            result = await hass.config_entries.flow.async_configure(flow_id, data)
        if result["type"] is FlowResultType.CREATE_ENTRY:
            entry = result["result"]
            existing = _existing_result(hass, normalized)
            if existing is not None:
                return WolResult(
                    status="created"
                    if existing.status == "reused"
                    else existing.status,
                    mac=normalized,
                    entity_registry_id=existing.entity_registry_id,
                    entry_id=entry.entry_id,
                )
            return WolResult(status="pending", mac=normalized, entry_id=entry.entry_id)
        if (
            result["type"] is FlowResultType.ABORT
            and result.get("reason") == "already_configured"
        ):
            return _existing_result(hass, normalized) or WolResult(
                status="pending", mac=normalized, reason="already_configured"
            )
        if result["type"] is FlowResultType.FORM:
            hass.config_entries.flow.async_abort(result["flow_id"])
        return WolResult(status="error", mac=normalized, reason="native_flow_failed")
    except (HomeAssistantError, InvalidData, ValueError):
        if flow_id is not None and any(
            flow["flow_id"] == flow_id
            for flow in hass.config_entries.flow.async_progress()
        ):
            hass.config_entries.flow.async_abort(flow_id)
        return _existing_result(hass, normalized) or WolResult(
            status="error", mac=normalized, reason="native_flow_failed"
        )
