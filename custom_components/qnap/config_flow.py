"""Config flow to configure qnap component."""

from __future__ import annotations

import logging
from typing import Any

from qnap_client import (
    QnapAuthError,
    QnapClient,
    QnapConnectionError,
    QnapError,
    QnapTimeoutError,
)
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_WOL_CANDIDATES,
    CONF_WOL_ENTITIES,
    CONF_WOL_ENTRY_IDS,
    CONF_WOL_SUGGESTIONS_DISMISSED,
    DEFAULT_PORT,
    DEFAULT_SSL,
    DEFAULT_TIMEOUT,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .wol import get_mac_candidates
from .wol_flow import QnapWolFlowMixin

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_SSL, default=DEFAULT_SSL): cv.boolean,
        vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): cv.boolean,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    }
)

_LOGGER = logging.getLogger(__name__)


class QnapConfigFlow(QnapWolFlowMixin, ConfigFlow, domain=DOMAIN):
    """Qnap configuration flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> QnapOptionsFlow:
        """Offer WOL setup independently from the NAS connection state."""
        return QnapOptionsFlow()

    async def _async_validate_input(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, str], dict[str, Any] | None]:
        """Validate user input by connecting to the QNAP device."""
        errors: dict[str, str] = {}
        client = QnapClient(
            host=user_input[CONF_HOST],
            port=user_input[CONF_PORT],
            username=user_input[CONF_USERNAME],
            password=user_input[CONF_PASSWORD],
            ssl=user_input[CONF_SSL],
            verify_ssl=user_input[CONF_VERIFY_SSL],
            timeout=DEFAULT_TIMEOUT,
        )
        try:
            async with client:
                info = await client.get_system_info()
                try:
                    interfaces = await client.get_network_interfaces()
                except QnapError:
                    interfaces = []
        except QnapAuthError:
            errors["base"] = "invalid_auth"
        except QnapConnectionError:
            errors["base"] = "cannot_connect"
        except QnapTimeoutError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error during QNAP setup validation")
            errors["base"] = "unknown"
        else:
            self._network_candidates = get_mac_candidates(interfaces)
            return errors, {"serial_number": info.serial_number, "name": info.name}
        return errors, None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, info = await self._async_validate_input(user_input)
            if not errors and info is not None:
                unique_id = info["serial_number"]
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                self._connection_input = dict(user_input)
                self._nas_title = info["name"]
                self._initialize_wol({CONF_WOL_CANDIDATES: self._network_candidates})
                return await self.async_step_wol()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(DATA_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the integration."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            errors, info = await self._async_validate_input(user_input)
            if not errors and info is not None:
                unique_id = info["serial_number"]
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_mismatch()
                self._connection_input = dict(user_input)
                self._wol_entry = reconfigure_entry
                self._initialize_wol(
                    {
                        **reconfigure_entry.options,
                        CONF_WOL_CANDIDATES: self._network_candidates,
                    }
                )
                if self._wol_options.get(CONF_WOL_SUGGESTIONS_DISMISSED):
                    return await self._async_finish_wol()
                return await self.async_step_wol()

        suggested_values: dict[str, Any] = dict(user_input or reconfigure_entry.data)
        suggested_values.pop(CONF_PASSWORD, None)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                DATA_SCHEMA,
                suggested_values,
            ),
            errors=errors,
        )

    async def _async_finish_wol(self) -> ConfigFlowResult:
        """Save a new NAS or finish reconfiguration after WOL consent."""
        if self._wol_entry is not None:
            self._save_wol_progress()
            return self.async_update_reload_and_abort(
                self._wol_entry, data_updates=self._connection_input
            )
        return self.async_create_entry(
            title=self._nas_title,
            data=self._connection_input,
            options=self._wol_options,
        )


class QnapOptionsFlow(QnapWolFlowMixin, OptionsFlow):
    """Configure native WOL associations with the NAS online or offline."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Load saved candidates and supplement them with current monitor data."""
        self._wol_entry = self.config_entry
        options = dict(self.config_entry.options)
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is not None and coordinator.data is not None:
            options[CONF_WOL_CANDIDATES] = get_mac_candidates(
                coordinator.data.network_interfaces
            )
        self._initialize_wol(options)
        return await self.async_step_wol(user_input)

    async def _async_finish_wol(self) -> ConfigFlowResult:
        """Save only this NAS's associations and suggestion preference."""
        self._save_wol_progress()
        if (
            self.config_entry.state is ConfigEntryState.SETUP_RETRY
            and self.config_entry.disabled_by is None
            and (
                self._wol_options.get(CONF_WOL_ENTITIES)
                or self._wol_options.get(CONF_WOL_ENTRY_IDS)
            )
        ):
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
        return self.async_create_entry(title="", data=self._wol_options)
