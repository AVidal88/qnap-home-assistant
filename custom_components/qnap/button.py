"""Support for QNAP power buttons."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_WOL_ENTITIES, CONF_WOL_ENTRY_IDS, DOMAIN
from .coordinator import QnapConfigEntry, QnapCoordinator
from .wol import resolve_wol_entities


@dataclass(frozen=True, kw_only=True)
class QnapPowerButtonDescription(ButtonEntityDescription):
    """Describe a supported QTS power action."""

    key: Literal["shutdown", "reboot"]


BUTTONS: tuple[QnapPowerButtonDescription, ...] = (
    QnapPowerButtonDescription(
        key="shutdown",
        translation_key="shutdown",
        icon="mdi:power",
    ),
    QnapPowerButtonDescription(
        key="reboot",
        translation_key="reboot",
        device_class=ButtonDeviceClass.RESTART,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: QnapConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up QNAP power button entities."""
    coordinator = config_entry.runtime_data
    unique_id = config_entry.unique_id
    assert unique_id is not None

    async_add_entities(
        [
            QNAPWakeButton(config_entry, unique_id),
            *(
                QNAPPowerButton(coordinator, unique_id, description)
                for description in BUTTONS
            ),
        ]
    )


class QNAPWakeButton(ButtonEntity):
    """Delegate wake requests to explicitly associated native WOL buttons."""

    _attr_has_entity_name = True
    _attr_translation_key = "wake"
    _attr_icon = "mdi:power"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, config_entry: QnapConfigEntry, unique_id: str) -> None:
        """Keep the selected native entities independent of NAS monitoring."""
        self._config_entry = config_entry
        self._attr_unique_id = f"{unique_id}_wake"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)}, name=config_entry.title
        )
        self._unsub_states: Callable[[], None] | None = None

    def _resolve_targets(self) -> list[er.RegistryEntry]:
        """Resolve current entity IDs from persisted registry identities."""
        options = self._config_entry.options
        return resolve_wol_entities(
            self.hass,
            options.get(CONF_WOL_ENTITIES, []),
            options.get(CONF_WOL_ENTRY_IDS, []),
        )

    @property
    def available(self) -> bool:
        """Require the complete selected set of enabled native WOL targets."""
        targets = self._resolve_targets()
        if not targets:
            return False
        options = self._config_entry.options
        if not set(options.get(CONF_WOL_ENTITIES, [])).issubset(
            {target.id for target in targets}
        ):
            return False
        if not set(options.get(CONF_WOL_ENTRY_IDS, [])).issubset(
            {target.config_entry_id for target in targets}
        ):
            return False
        for target in targets:
            entry = self.hass.config_entries.async_get_entry(target.config_entry_id)
            state = self.hass.states.get(target.entity_id)
            if (
                target.disabled_by is not None
                or entry is None
                or entry.disabled_by is not None
                or state is None
                or state.state == STATE_UNAVAILABLE
            ):
                return False
        return True

    async def async_added_to_hass(self) -> None:
        """Listen to native entity lifecycle and load configured targets."""
        self.async_on_remove(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._async_registry_changed
            )
        )
        self.async_on_remove(
            self._config_entry.add_update_listener(self._async_options_changed)
        )
        self.async_on_remove(self._async_unsubscribe_states)
        self._async_track_targets()
        await self._async_load_targets()
        self._async_track_targets()

    async def _async_load_targets(self) -> None:
        """Load selected configured WOL entries without changing their settings."""
        entry_ids = set(self._config_entry.options.get(CONF_WOL_ENTRY_IDS, []))
        entry_ids.update(target.config_entry_id for target in self._resolve_targets())
        for entry_id in entry_ids:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if (
                entry is not None
                and entry.domain == "wake_on_lan"
                and entry.disabled_by is None
                and entry.state is ConfigEntryState.NOT_LOADED
            ):
                await self.hass.config_entries.async_setup(entry_id)

    async def _async_options_changed(
        self, hass: HomeAssistant, entry: QnapConfigEntry
    ) -> None:
        """Refresh associations after the user changes this NAS's options."""
        await self._async_load_targets()
        self._async_track_targets()
        self.async_write_ha_state()

    @callback
    def _async_unsubscribe_states(self) -> None:
        """Release the current native state listeners."""
        if self._unsub_states is not None:
            self._unsub_states()
            self._unsub_states = None

    @callback
    def _async_track_targets(self) -> None:
        """Follow the selected registry identities through entity renames."""
        self._async_unsubscribe_states()
        entity_ids = [target.entity_id for target in self._resolve_targets()]
        if entity_ids:
            self._unsub_states = async_track_state_change_event(
                self.hass, entity_ids, self._async_target_state_changed
            )

    @callback
    def _async_registry_changed(self, event: Event) -> None:
        """Update target tracking after registry creation, removal or renaming."""
        self._async_track_targets()
        self.async_write_ha_state()

    @callback
    def _async_target_state_changed(self, event: Event) -> None:
        """Update availability when a native button loads or becomes unavailable."""
        self.async_write_ha_state()

    async def async_press(self) -> None:
        """Invoke native button.press once for the complete associated set."""
        if not self.available:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="wake_unavailable",
            )
        entity_ids = [target.entity_id for target in self._resolve_targets()]
        try:
            await self.hass.services.async_call(
                "button",
                "press",
                {ATTR_ENTITY_ID: entity_ids},
                blocking=True,
                context=self._context,
            )
        except Exception:  # noqa: BLE001
            # Some native targets may already have run. A retry needs a new press.
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="wake_failed",
            ) from None


class QNAPPowerButton(CoordinatorEntity[QnapCoordinator], ButtonEntity):
    """A button requesting a QTS power action."""

    entity_description: QnapPowerButtonDescription
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: QnapCoordinator,
        unique_id: str,
        description: QnapPowerButtonDescription,
    ) -> None:
        """Initialize the power button."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{unique_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            name=(
                coordinator.data.system_info.name
                if coordinator.data is not None
                else coordinator.config_entry.title
            ),
        )

    async def async_press(self) -> None:
        """Request one power action through the coordinator."""
        await self.coordinator.async_power_action(self.entity_description.key)
