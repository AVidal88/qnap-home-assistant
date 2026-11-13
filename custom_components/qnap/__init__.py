"""The qnap component."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_WOL_ENTITIES, CONF_WOL_ENTRY_IDS
from .coordinator import QnapConfigEntry, QnapCoordinator

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]


async def async_setup_entry(hass: HomeAssistant, config_entry: QnapConfigEntry) -> bool:
    """Set the config entry up."""
    coordinator = QnapCoordinator(hass, config_entry)
    try:
        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryNotReady:
            if not (
                config_entry.options.get(CONF_WOL_ENTITIES)
                or config_entry.options.get(CONF_WOL_ENTRY_IDS)
            ):
                raise
            # A persisted WOL association must load even while QTS is offline.
            # Coordinator listeners keep read-only recovery polling scheduled.
        config_entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    except BaseException:
        await coordinator.async_close()
        raise
    return True


async def async_unload_entry(
    hass: HomeAssistant, config_entry: QnapConfigEntry
) -> bool:
    """Unload a config entry."""
    if await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS):
        await config_entry.runtime_data.async_close()
        return True
    return False
