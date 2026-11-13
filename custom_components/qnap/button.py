"""Support for QNAP power buttons."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import QnapConfigEntry, QnapCoordinator


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
        QNAPPowerButton(coordinator, unique_id, description) for description in BUTTONS
    )


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
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, unique_id)})

    async def async_press(self) -> None:
        """Request one power action through the coordinator."""
        await self.coordinator.async_power_action(self.entity_description.key)
