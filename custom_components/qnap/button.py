"""Wake-on-LAN button for a QNAP NAS."""

from __future__ import annotations

from functools import partial

import wakeonlan
from homeassistant.components.button import ButtonEntity
from homeassistant.const import CONF_BROADCAST_ADDRESS, CONF_BROADCAST_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_WOL_MACS,
    DEFAULT_BROADCAST_ADDRESS,
    DEFAULT_BROADCAST_PORT,
    DOMAIN,
)
from .coordinator import QnapConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: QnapConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Wake-on-LAN when physical MAC addresses are configured."""
    if config_entry.options.get(CONF_WOL_MACS):
        async_add_entities([QNAPWakeButton(config_entry)])


class QNAPWakeButton(ButtonEntity):
    """Send magic packets without requiring a connection to QTS."""

    _attr_has_entity_name = True
    _attr_translation_key = "wake"
    _attr_icon = "mdi:power"

    def __init__(self, config_entry: QnapConfigEntry) -> None:
        """Remember configuration locally so an offline NAS can be woken."""
        uid = config_entry.unique_id
        assert uid is not None
        self._attr_unique_id = f"{uid}_wake"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, uid)}, name=config_entry.title
        )
        self._mac_addresses = tuple(config_entry.options[CONF_WOL_MACS])
        self._broadcast_address = config_entry.options.get(
            CONF_BROADCAST_ADDRESS, DEFAULT_BROADCAST_ADDRESS
        )
        self._broadcast_port = config_entry.options.get(
            CONF_BROADCAST_PORT, DEFAULT_BROADCAST_PORT
        )

    async def async_press(self) -> None:
        """Send one magic packet for each configured interface."""
        try:
            await self.hass.async_add_executor_job(
                partial(
                    wakeonlan.send_magic_packet,
                    *self._mac_addresses,
                    ip_address=self._broadcast_address,
                    port=self._broadcast_port,
                )
            )
        except OSError:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="wake_failed"
            ) from None
