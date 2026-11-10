"""Data coordinator for the qnap integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_TIMEOUT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from qnap_client import ContainerStationClient, QnapAuthError, QnapClient, QnapError
from qnap_client.models import NasData

from .const import (
    DEFAULT_PORT,
    DEFAULT_SSL,
    DEFAULT_TIMEOUT,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

type QnapConfigEntry = ConfigEntry[QnapCoordinator]

UPDATE_INTERVAL = timedelta(minutes=5)

_LOGGER = logging.getLogger(__name__)


class QnapCoordinator(DataUpdateCoordinator[NasData]):
    """Custom coordinator for the qnap integration."""

    config_entry: QnapConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: QnapConfigEntry) -> None:
        """Initialize the qnap coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )

        self._api = QnapClient(
            host=config_entry.data[CONF_HOST],
            port=config_entry.data.get(CONF_PORT, DEFAULT_PORT),
            username=config_entry.data[CONF_USERNAME],
            password=config_entry.data[CONF_PASSWORD],
            ssl=config_entry.data.get(CONF_SSL, DEFAULT_SSL),
            verify_ssl=config_entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            timeout=config_entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
        )
        self._cs = ContainerStationClient(self._api)
        self._authenticated = False

    async def async_close(self) -> None:
        """Release the HTTP session without making another request to the NAS."""
        await self.async_shutdown()
        await self._api.close(logout=False)

    async def _async_update_data(self) -> NasData:
        """Authenticate as needed, then fetch NAS data without retrying requests."""
        try:
            if not self._authenticated:
                await self._api.login()
                self._authenticated = True
            data = await self._api.get_all()
        except QnapAuthError:
            self._authenticated = False
            # Keep the entry loaded so WOL remains usable with invalid credentials.
            raise UpdateFailed("QNAP authentication failed") from None
        except QnapError:
            self._authenticated = False
            raise UpdateFailed("Unable to fetch QNAP data") from None

        # Container Station — non-fatal
        try:
            data.containers = await self._cs.get_containers()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Container Station unavailable (%s)", type(err).__name__)
            data.containers = getattr(self.data, "containers", []) if self.data else []

        return data
