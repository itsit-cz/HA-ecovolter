"""Config flow for EcoVolter."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    EcoVolterApi,
    EcoVolterAuthError,
    EcoVolterConnectionError,
    EcoVolterError,
)
from .scheduler import parse_vt_windows
from .const import (
    CONF_DISTRIBUTION_NT,
    CONF_DISTRIBUTION_VT,
    CONF_PRICE_ENTITY,
    CONF_SCAN_INTERVAL,
    CONF_VT_WINDOWS,
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
    """EcoVolter options: refresh interval and scheduler price settings."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                parse_vt_windows(user_input.get(CONF_VT_WINDOWS, ""))
            except ValueError:
                errors[CONF_VT_WINDOWS] = "invalid_vt_windows"
            else:
                return self.async_create_entry(data=user_input)

        opts = {**self.config_entry.options, **(user_input or {})}
        price_key = (
            vol.Optional(CONF_PRICE_ENTITY, description={"suggested_value": opts[CONF_PRICE_ENTITY]})
            if opts.get(CONF_PRICE_ENTITY)
            else vol.Optional(CONF_PRICE_ENTITY)
        )
        price_number = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=20, step=0.001, unit_of_measurement="CZK/kWh",
                mode=selector.NumberSelectorMode.BOX,
            )
        )
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                    price_key: selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor")
                    ),
                    vol.Required(
                        CONF_DISTRIBUTION_VT, default=opts.get(CONF_DISTRIBUTION_VT, 0.0)
                    ): price_number,
                    vol.Required(
                        CONF_DISTRIBUTION_NT, default=opts.get(CONF_DISTRIBUTION_NT, 0.0)
                    ): price_number,
                    vol.Optional(
                        CONF_VT_WINDOWS, default=opts.get(CONF_VT_WINDOWS, "")
                    ): selector.TextSelector(),
                }
            ),
        )
