"""Config flow to configure qnap component."""

from __future__ import annotations

import logging
import re
from ipaddress import IPv4Address
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_BROADCAST_ADDRESS,
    CONF_BROADCAST_PORT,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig
from qnap_client import QnapAuthError, QnapClient, QnapConnectionError, QnapTimeoutError

from .const import (
    CONF_WOL_MACS,
    DEFAULT_BROADCAST_ADDRESS,
    DEFAULT_BROADCAST_PORT,
    DEFAULT_PORT,
    DEFAULT_SSL,
    DEFAULT_TIMEOUT,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

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


def normalize_mac_addresses(value: list[str]) -> list[str]:
    """Validate physical unicast MAC addresses and remove duplicates."""
    if not isinstance(value, list):
        raise TypeError("MAC addresses must be a list")
    normalized: list[str] = []
    for mac in value:
        if not isinstance(mac, str):
            raise TypeError("Invalid MAC address")
        mac = mac.strip()
        if not re.fullmatch(
            r"(?:[0-9a-f]{12}|[0-9a-f]{2}([:-])(?:[0-9a-f]{2}\1){4}[0-9a-f]{2})",
            mac,
            re.IGNORECASE,
        ):
            raise ValueError("Invalid MAC address")
        octets = bytes.fromhex(mac.replace(":", "").replace("-", ""))
        if not any(octets) or octets[0] & 1:
            raise ValueError("A physical unicast MAC address is required")
        canonical = ":".join(f"{octet:02x}" for octet in octets)
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


def normalize_broadcast_address(value: str) -> str:
    """Validate an IPv4 destination without resolving a hostname."""
    if not isinstance(value, str):
        raise TypeError("An IPv4 broadcast destination is required")
    address = IPv4Address(value.strip())
    if address.is_unspecified or address.is_loopback or address.is_multicast:
        raise ValueError("An IPv4 broadcast destination is required")
    return str(address)


class QnapConfigFlow(ConfigFlow, domain=DOMAIN):
    """Qnap configuration flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> QnapOptionsFlow:
        """Return the options flow, which does not need a QTS connection."""
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
        except QnapAuthError:
            errors["base"] = "invalid_auth"
        except QnapConnectionError:
            errors["base"] = "cannot_connect"
        except QnapTimeoutError:
            errors["base"] = "cannot_connect"
        except Exception:  # noqa: BLE001
            # Exception details can contain QTS credentials or session identifiers.
            _LOGGER.error("Unexpected error during QNAP setup validation")
            errors["base"] = "unknown"
        else:
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
                title = info["name"]
                return self.async_create_entry(title=title, data=user_input)

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
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data_updates=user_input,
                )

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


class QnapOptionsFlow(OptionsFlowWithReload):
    """Configure Wake-on-LAN independently of the NAS connection."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage Wake-on-LAN settings, including while the NAS is offline."""
        errors: dict[str, str] = {}
        if user_input is not None:
            options = dict(user_input)
            try:
                options[CONF_WOL_MACS] = normalize_mac_addresses(
                    user_input.get(CONF_WOL_MACS, [])
                )
            except (TypeError, ValueError):
                errors[CONF_WOL_MACS] = "invalid_mac"
            try:
                options[CONF_BROADCAST_ADDRESS] = normalize_broadcast_address(
                    user_input.get(CONF_BROADCAST_ADDRESS, DEFAULT_BROADCAST_ADDRESS)
                )
            except (TypeError, ValueError):
                errors[CONF_BROADCAST_ADDRESS] = "invalid_broadcast_address"
            port = user_input.get(CONF_BROADCAST_PORT, DEFAULT_BROADCAST_PORT)
            if (
                isinstance(port, bool)
                or not isinstance(port, int)
                or not 1 <= port <= 65535
            ):
                errors[CONF_BROADCAST_PORT] = "invalid_broadcast_port"
            if not errors:
                options[CONF_BROADCAST_PORT] = port
                return self.async_create_entry(
                    title="", data={**self.config_entry.options, **options}
                )

        schema = vol.Schema(
            {
                vol.Optional(CONF_WOL_MACS, default=list): TextSelector(
                    TextSelectorConfig(multiple=True)
                ),
                vol.Required(
                    CONF_BROADCAST_ADDRESS, default=DEFAULT_BROADCAST_ADDRESS
                ): cv.string,
                vol.Required(
                    CONF_BROADCAST_PORT, default=DEFAULT_BROADCAST_PORT
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                user_input if user_input is not None else self.config_entry.options,
            ),
            errors=errors,
        )
