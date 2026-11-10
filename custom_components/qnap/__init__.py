"""The qnap component."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

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
    config_entry.runtime_data = coordinator
    try:
        # Existing entries must load even when the NAS is off: WOL needs no QTS.
        await coordinator.async_refresh()
        await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    except BaseException:
        await coordinator.async_close()
        raise
    return True


async def async_unload_entry(
    hass: HomeAssistant, config_entry: QnapConfigEntry
) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    ):
        await config_entry.runtime_data.async_close()
    return unload_ok
