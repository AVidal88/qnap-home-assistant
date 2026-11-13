"""Data coordinator for the qnap integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Literal

from qnap_client import (
    ContainerStationClient,
    QnapAuthError,
    QnapClient,
    QnapError,
    QnapPermissionError,
    QnapPowerOutcomeUnknown,
    QnapPowerRejectedError,
)
from qnap_client.models import NasData

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
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

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

        self._api = self._create_client()
        self._cs = ContainerStationClient(self._api)
        self._monitor_lock = asyncio.Lock()
        self._monitor_stopped = False
        self._monitor_closed = False
        self._power_lock = asyncio.Lock()

    def _create_client(self) -> QnapClient:
        """Create an owned client with this entry's connection settings."""
        data = self.config_entry.data
        return QnapClient(
            host=data[CONF_HOST],
            port=data.get(CONF_PORT, DEFAULT_PORT),
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            ssl=data.get(CONF_SSL, DEFAULT_SSL),
            verify_ssl=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            timeout=data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
        )

    async def async_close(self) -> None:
        """Close the owned monitoring session without another NAS request."""
        await self.async_shutdown()

    async def async_shutdown(self) -> None:
        """Stop polling and wait for in-flight reads before closing the client."""
        self._monitor_stopped = True
        await super().async_shutdown()
        async with self._monitor_lock:
            if not self._monitor_closed:
                await self._api.close(logout=False)
                self._monitor_closed = True

    async def async_power_action(self, action: Literal["shutdown", "reboot"]) -> None:
        """Request one QTS power action using an independent session."""
        if self._power_lock.locked():
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="power_in_progress",
            )

        async with self._power_lock:
            client = self._create_client()
            try:
                await client.login()
                if action == "shutdown":
                    await client.shutdown()
                else:
                    await client.reboot()
            except QnapAuthError:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="authentication_failed",
                ) from None
            except QnapPermissionError:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="permission_denied",
                ) from None
            except QnapPowerRejectedError:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="power_rejected",
                ) from None
            except QnapPowerOutcomeUnknown:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="power_outcome_unknown",
                ) from None
            except QnapError:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="power_failed",
                ) from None
            finally:
                try:
                    await client.close(logout=False)
                except Exception:  # noqa: BLE001
                    # Cleanup must preserve an acknowledgement or earlier error.
                    _LOGGER.warning("Unable to close the QNAP power HTTP session")

    async def _async_setup(self) -> None:
        """Authenticate on first setup."""
        async with self._monitor_lock:
            if self._monitor_stopped:
                raise ConfigEntryNotReady("QNAP monitoring has stopped")
            try:
                await self._api.login()
            except QnapError:
                raise ConfigEntryNotReady("Cannot connect to QNAP NAS") from None

    async def _async_update_data(self) -> NasData:
        """Fetch all NAS data."""
        async with self._monitor_lock:
            if self._monitor_stopped:
                raise UpdateFailed("QNAP monitoring has stopped")
            try:
                # get_all() replaces individual failures with empty data, so probe
                # explicitly before treating an unavailable NAS as a valid update.
                try:
                    system_info = await self._api.get_system_info()
                except QnapAuthError:
                    system_info = None

                if system_info is None or not system_info.serial_number:
                    # Some expired QTS sessions yield an empty identity without an
                    # HTTP authentication error. Renew once, without logging out.
                    await self._api.login()
                    system_info = await self._api.get_system_info()

                if not system_info.serial_number:
                    raise UpdateFailed("QNAP system identity is unavailable")
                if (
                    self.config_entry.unique_id is not None
                    and system_info.serial_number != self.config_entry.unique_id
                ):
                    raise UpdateFailed("QNAP system identity does not match this entry")

                data = await self._api.get_all()
                if not data.system_info.serial_number:
                    raise UpdateFailed("QNAP system identity is unavailable")
                if data.system_info.serial_number != system_info.serial_number:
                    raise UpdateFailed("QNAP system identity does not match this entry")
            except QnapAuthError:
                raise UpdateFailed("QNAP authentication failed") from None
            except QnapError:
                raise UpdateFailed("Error fetching QNAP data") from None

            # Container Station — non-fatal
            try:
                data.containers = await self._cs.get_containers()
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Container Station unavailable: %s", err)
                data.containers = (
                    getattr(self.data, "containers", []) if self.data else []
                )

            return data
