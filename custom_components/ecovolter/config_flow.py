"""Config flow for EcoVolter."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    EcoVolterApi,
    EcoVolterAuthError,
    EcoVolterConnectionError,
    EcoVolterError,
)
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_SECRET,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)


class EcoVolterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle EcoVolter configuration."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> EcoVolterOptionsFlow:
        return EcoVolterOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            secret = user_input[CONF_SECRET].strip()
            api = EcoVolterApi(async_get_clientsession(self.hass), host, secret)

            try:
                diagnostic = await api.async_get_diagnostic()
                await api.async_get_status()
            except EcoVolterAuthError:
                errors["base"] = "invalid_auth"
            except EcoVolterConnectionError:
                errors["base"] = "cannot_connect"
            except EcoVolterError:
                errors["base"] = "unknown"
            else:
                serial = (
                    diagnostic.get("serialNumber")
                    or diagnostic.get("serial")
                    or diagnostic.get("deviceSerialNumber")
                )
                unique_id = str(serial or host).lower()
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"EcoVolter {serial}" if serial else f"EcoVolter {host}",
                    data={CONF_HOST: host, CONF_SECRET: secret},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_SECRET): str,
                }
            ),
            errors=errors,
        )


class EcoVolterOptionsFlow(config_entries.OptionsFlow):
    """EcoVolter options (refresh interval)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                }
            ),
        )
