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
from .scheduler import PRICE_FIXED, PRICE_SENSOR, parse_vt_windows
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


PRICE_NUMBER = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0, max=30, step=0.001, unit_of_measurement="Kč/kWh",
        mode=selector.NumberSelectorMode.BOX,
    )
)


def _entity(key: str, opts: dict[str, Any], domain: list[str] | str, device_class=None):
    """Optional entity selector that keeps the current value and can be cleared."""
    marker = (
        vol.Optional(key, description={"suggested_value": opts[key]})
        if opts.get(key)
        else vol.Optional(key)
    )
    config = selector.EntitySelectorConfig(domain=domain)
    if device_class:
        config = selector.EntitySelectorConfig(domain=domain, device_class=device_class)
    return marker, selector.EntitySelector(config)


def _price_type_schema(opts: dict[str, Any]) -> dict:
    return {
        vol.Required("price_type", default=opts.get("price_type", PRICE_SENSOR)): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[PRICE_SENSOR, PRICE_FIXED],
                translation_key="price_type",
                mode=selector.SelectSelectorMode.LIST,
            )
        )
    }


def _prices_schema(opts: dict[str, Any]) -> dict:
    schema: dict = {}
    if opts.get("price_type", PRICE_SENSOR) == PRICE_SENSOR:
        key, sel = _entity(CONF_PRICE_ENTITY, opts, "sensor")
        schema[key] = sel
    else:
        schema[vol.Required("energy_vt", default=opts.get("energy_vt", 0.0))] = PRICE_NUMBER
        schema[vol.Required("energy_nt", default=opts.get("energy_nt", 0.0))] = PRICE_NUMBER
    schema[vol.Required(CONF_DISTRIBUTION_VT, default=opts.get(CONF_DISTRIBUTION_VT, 0.0))] = PRICE_NUMBER
    schema[vol.Required(CONF_DISTRIBUTION_NT, default=opts.get(CONF_DISTRIBUTION_NT, 0.0))] = PRICE_NUMBER
    return schema


def _tariff_schema(opts: dict[str, Any]) -> dict:
    key, sel = _entity("hdo_entity", opts, ["sensor", "binary_sensor"])
    return {
        key: sel,
        vol.Optional(CONF_VT_WINDOWS, default=opts.get(CONF_VT_WINDOWS, "")): selector.TextSelector(),
    }


def _car_schema(opts: dict[str, Any]) -> dict:
    key, sel = _entity("soc_entity", opts, "sensor", device_class="battery")
    return {
        key: sel,
        vol.Optional("battery_kwh", default=opts.get("battery_kwh", 0.0)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=250, step=0.1, unit_of_measurement="kWh", mode=selector.NumberSelectorMode.BOX)
        ),
        vol.Optional("charging_efficiency", default=opts.get("charging_efficiency", 90)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=50, max=100, step=1, unit_of_measurement="%", mode=selector.NumberSelectorMode.BOX)
        ),
    }


def _clean(user_input: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """Drop cleared optional entity fields so they really get removed."""
    return {k: v for k, v in user_input.items() if not (k in keys and not v)}


class _SchedulerSteps:
    """Shared steps for the initial setup and the options flow."""

    _opts: dict[str, Any]

    def _finish(self) -> FlowResult:  # implemented by the flows
        raise NotImplementedError

    async def async_step_price_type(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._opts.update(user_input)
            return await self.async_step_prices()
        return self.async_show_form(step_id="price_type", data_schema=vol.Schema(_price_type_schema(self._opts)))

    async def async_step_prices(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._opts = {k: v for k, v in self._opts.items() if k != CONF_PRICE_ENTITY}
            self._opts.update(_clean(user_input, (CONF_PRICE_ENTITY,)))
            return await self.async_step_tariff()
        return self.async_show_form(step_id="prices", data_schema=vol.Schema(_prices_schema(self._opts)))

    async def async_step_tariff(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                parse_vt_windows(user_input.get(CONF_VT_WINDOWS, ""))
            except ValueError:
                errors[CONF_VT_WINDOWS] = "invalid_vt_windows"
            else:
                self._opts = {k: v for k, v in self._opts.items() if k != "hdo_entity"}
                self._opts.update(_clean(user_input, ("hdo_entity",)))
                return await self.async_step_car()
        return self.async_show_form(
            step_id="tariff", data_schema=vol.Schema(_tariff_schema({**self._opts, **(user_input or {})})), errors=errors
        )

    async def async_step_car(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._opts = {k: v for k, v in self._opts.items() if k != "soc_entity"}
            self._opts.update(_clean(user_input, ("soc_entity",)))
            return self._finish()
        return self.async_show_form(step_id="car", data_schema=vol.Schema(_car_schema(self._opts)))


class EcoVolterConfigFlow(_SchedulerSteps, config_entries.ConfigFlow, domain=DOMAIN):
    """Handle EcoVolter configuration."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._title = "EcoVolter"
        self._opts: dict[str, Any] = {}

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
                self._data = {CONF_HOST: host, CONF_SECRET: secret}
                self._title = f"EcoVolter {serial}" if serial else f"EcoVolter {host}"
                return await self.async_step_price_type()

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

    def _finish(self) -> FlowResult:
        return self.async_create_entry(title=self._title, data=self._data, options=self._opts)


class EcoVolterOptionsFlow(_SchedulerSteps, config_entries.OptionsFlow):
    """EcoVolter options: refresh interval, prices, tariff times, car."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._opts = dict(self.config_entry.options)
        if user_input is not None:
            self._opts.update(user_input)
            return await self.async_step_prices()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self._opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                    **_price_type_schema(self._opts),
                }
            ),
        )

    def _finish(self) -> FlowResult:
        return self.async_create_entry(data=self._opts)
