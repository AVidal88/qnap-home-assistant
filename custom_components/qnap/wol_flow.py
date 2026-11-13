"""Shared, consent-based setup of native Wake on LAN entries."""

from __future__ import annotations

from ipaddress import IPv4Address
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector

from .const import (
    CONF_WOL_CANDIDATES,
    CONF_WOL_ENTITIES,
    CONF_WOL_ENTRY_IDS,
    CONF_WOL_MACS,
    CONF_WOL_SUGGESTIONS_DISMISSED,
)
from .wol import async_ensure_wol, normalize_mac, resolve_wol_entities

CONF_CREATE_MISSING = "create_missing"
CONF_MANUAL_MACS = "manual_macs"
CONF_CONFIRM_CREATE = "confirm_create"


class QnapWolFlowMixin:
    """Coordinate native WOL from both QNAP setup and its options flow."""

    hass: HomeAssistant
    _wol_entry: ConfigEntry | None = None

    def _initialize_wol(self, options: dict[str, Any]) -> None:
        """Keep editable options separate from the persisted config entry."""
        self._wol_options = dict(options)
        self._wol_pending: list[str] = []
        self._wol_results: dict[str, str] = {}
        self._wol_candidates = list(options.get(CONF_WOL_CANDIDATES, []))
        self._wol_options[CONF_WOL_CANDIDATES] = [
            {"mac": item["mac"], "name": item["name"]} for item in self._wol_candidates
        ]

    def _save_wol_progress(self) -> None:
        """Persist completed associations before attempting another interface."""
        if self._wol_entry is not None:
            self.hass.config_entries.async_update_entry(
                self._wol_entry, options=dict(self._wol_options)
            )

    def _remember_wol(self, registry_id: str | None, entry_id: str | None) -> None:
        """Record identities without storing another integration's settings."""
        for key, value in (
            (CONF_WOL_ENTITIES, registry_id),
            (CONF_WOL_ENTRY_IDS, entry_id),
        ):
            values = list(self._wol_options.get(key, []))
            if value is not None and value not in values:
                values.append(value)
            self._wol_options[key] = values
        self._save_wol_progress()

    async def async_step_wol(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select physical MACs and existing native buttons explicitly."""
        candidates = self._wol_candidates
        confirmed = self._wol_options.get(CONF_WOL_MACS, [])
        choices = {
            item["mac"]: f"{item['name']} ({item['mac']})" for item in candidates
        }
        choices.update({mac: choices.get(mac, mac) for mac in confirmed})
        associated = resolve_wol_entities(
            self.hass,
            self._wol_options.get(CONF_WOL_ENTITIES, []),
            self._wol_options.get(CONF_WOL_ENTRY_IDS, []),
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = list(user_input.get(CONF_WOL_MACS, confirmed))
            selected.extend(
                value.strip()
                for value in user_input.get(CONF_MANUAL_MACS, "").split(",")
                if value.strip()
            )
            macs = [normalize_mac(value) for value in selected]
            if None in macs:
                errors[CONF_MANUAL_MACS] = "invalid_mac"
            selected_entities = user_input.get(
                CONF_WOL_ENTITIES, [entity.entity_id for entity in associated]
            )
            resolved = resolve_wol_entities(self.hass, selected_entities)
            if CONF_WOL_ENTITIES in user_input and len(resolved) != len(
                set(selected_entities)
            ):
                errors[CONF_WOL_ENTITIES] = "invalid_wol_entity"
            if not errors:
                self._wol_options[CONF_WOL_MACS] = list(dict.fromkeys(macs))
                if CONF_WOL_ENTITIES in user_input:
                    self._wol_options[CONF_WOL_ENTITIES] = [
                        entity.id for entity in resolved
                    ]
                    self._wol_options[CONF_WOL_ENTRY_IDS] = list(
                        dict.fromkeys(entity.config_entry_id for entity in resolved)
                    )
                else:
                    self._wol_options.setdefault(CONF_WOL_ENTITIES, [])
                    self._wol_options.setdefault(CONF_WOL_ENTRY_IDS, [])
                self._wol_options[CONF_WOL_SUGGESTIONS_DISMISSED] = user_input.get(
                    CONF_WOL_SUGGESTIONS_DISMISSED,
                    self._wol_options.get(CONF_WOL_SUGGESTIONS_DISMISSED, False),
                )
                self._wol_pending = []
                self._wol_results = {}
                for mac in self._wol_options[CONF_WOL_MACS]:
                    result = await async_ensure_wol(self.hass, mac)
                    self._wol_results[mac] = result.status
                    self._remember_wol(result.entity_registry_id, result.entry_id)
                    if result.status == "missing" and user_input.get(
                        CONF_CREATE_MISSING
                    ):
                        self._wol_pending.append(mac)
                self._save_wol_progress()
                return await self.async_step_wol_create()

        schema = vol.Schema(
            {
                vol.Optional(CONF_WOL_MACS, default=confirmed): cv.multi_select(
                    choices
                ),
                vol.Optional(CONF_MANUAL_MACS, default=""): cv.string,
                vol.Optional(
                    CONF_WOL_ENTITIES,
                    description={
                        "suggested_value": [entity.entity_id for entity in associated]
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="button", integration="wake_on_lan", multiple=True
                    )
                ),
                vol.Optional(CONF_CREATE_MISSING, default=False): cv.boolean,
                vol.Optional(
                    CONF_WOL_SUGGESTIONS_DISMISSED,
                    default=self._wol_options.get(
                        CONF_WOL_SUGGESTIONS_DISMISSED, False
                    ),
                ): cv.boolean,
            }
        )
        return self.async_show_form(step_id="wol", data_schema=schema, errors=errors)

    async def async_step_wol_create(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Review network settings and consent separately for each missing MAC."""
        if not self._wol_pending:
            if self._wol_results:
                return await self.async_step_wol_summary()
            return await self._async_finish_wol()
        mac = self._wol_pending[0]
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_CONFIRM_CREATE):
                address = user_input.get("broadcast_address", "").strip()
                try:
                    if address:
                        IPv4Address(address)
                except ValueError:
                    errors["broadcast_address"] = "invalid_broadcast"
                if not errors:
                    result = await async_ensure_wol(
                        self.hass,
                        mac,
                        consent=True,
                        broadcast_address=address or None,
                        broadcast_port=user_input.get("broadcast_port", 9),
                    )
                    self._wol_results[mac] = result.status
                    self._remember_wol(result.entity_registry_id, result.entry_id)
                    if result.status in {"error", "missing"}:
                        errors["base"] = "wol_creation_failed"
            if not errors:
                if not user_input.get(CONF_CONFIRM_CREATE):
                    self._wol_results[mac] = "skipped"
                self._wol_pending.pop(0)
                return await self.async_step_wol_create()

        suggested = next(
            (
                item.get("broadcast_address", "")
                for item in self._wol_candidates
                if item["mac"] == mac
            ),
            "",
        )
        return self.async_show_form(
            step_id="wol_create",
            data_schema=vol.Schema(
                {
                    vol.Optional("broadcast_address", default=suggested): cv.string,
                    vol.Optional("broadcast_port", default=9): vol.All(
                        vol.Coerce(int), vol.Range(min=0, max=65535)
                    ),
                    vol.Optional(CONF_CONFIRM_CREATE, default=False): cv.boolean,
                }
            ),
            errors=errors,
            description_placeholders={"mac": mac},
        )

    async def async_step_wol_summary(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Make partial creation and unresolved associations visible."""
        if user_input is not None:
            return await self._async_finish_wol()
        statuses = list(self._wol_results.values())
        return self.async_show_form(
            step_id="wol_summary",
            data_schema=vol.Schema({}),
            description_placeholders={
                "created": str(statuses.count("created")),
                "reused": str(statuses.count("reused")),
                "unavailable": str(
                    sum(
                        status in {"pending", "disabled", "error"}
                        for status in statuses
                    )
                ),
                "unconfigured": str(
                    sum(status in {"missing", "skipped"} for status in statuses)
                ),
            },
        )

    async def _async_finish_wol(self) -> ConfigFlowResult:
        """Complete the containing config or options flow."""
        raise NotImplementedError
