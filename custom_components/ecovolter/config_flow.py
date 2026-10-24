"""Config flow for EcoVolter.

Setup wizard (branches):

    connection -> tariff type
        spot  -> "final price incl. distribution and VAT?"
                    yes -> price sensor -> (VT/NT in the data? skip : VT/NT source)
                    no  -> spot sensor + markup + distribution + VAT -> VT/NT source
        two-rate    -> energy VT/NT + distribution VT/NT + VAT -> VT/NT source
        single rate -> energy + distribution + VAT
    VT/NT source: ČEZ (raw data sensor) / other HDO sensor / manual times
    -> cars (0–3) -> summary (prices incl. VAT, today's NT windows, cars)

The options flow is a menu: prices · VT/NT · cars · refresh interval.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

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
from .options import (
    DEFAULT_EFFICIENCY,
    DEFAULT_VAT,
    MAX_CARS,
    PRICE_FIXED1,
    PRICE_FIXED2,
    PRICE_SPOT,
    TARIFF_CEZ,
    TARIFF_DATA,
    TARIFF_MANUAL,
    TARIFF_NONE,
    TARIFF_SENSOR,
    normalize_car,
    normalize_options,
)
from .scheduler import (
    _find_cez_signals,
    build_slots,
    build_tariff,
    nt_windows_text,
    parse_hdo_windows,
    parse_prices,
    parse_vt_windows,
    price_list_attribute,
    slot_at,
)


def _money(step: float = 0.001, maximum: float = 30) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=maximum, step=step, unit_of_measurement="Kč/kWh",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


VAT_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(min=0, max=30, step=1, unit_of_measurement="%", mode=selector.NumberSelectorMode.BOX)
)


def _opt(key: str, opts: dict[str, Any]):
    """vol.Optional that pre-fills the current value but can be cleared."""
    if opts.get(key):
        return vol.Optional(key, description={"suggested_value": opts[key]})
    return vol.Optional(key)


def _req(key: str, opts: dict[str, Any], default: Any):
    return vol.Required(key, default=opts.get(key) if opts.get(key) not in (None, "") else default)


def _entity(domain: list[str] | str, device_class: str | None = None) -> selector.EntitySelector:
    if device_class:
        return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain, device_class=device_class))
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain))


def _fmt(value: float) -> str:
    """2 decimals, half up (6.655 -> 6,66), decimal comma."""
    from decimal import ROUND_HALF_UP, Decimal  # noqa: PLC0415

    return str(Decimal(repr(round(value, 6))).quantize(Decimal("0.01"), ROUND_HALF_UP)).replace(".", ",")


class _Wizard:
    """Steps shared by the setup and the options flow."""

    _opts: dict[str, Any]
    _is_options = False
    _car_index = 0
    _car_count = 0

    # implemented by the flows
    def _finish(self) -> FlowResult:
        raise NotImplementedError

    # ------------------------------------------------------------ tariff type

    async def async_step_tariff_type(self, user_input=None) -> FlowResult:
        return self.async_show_menu(step_id="tariff_type", menu_options=["spot", "fixed2", "fixed1"])

    async def async_step_spot(self, user_input=None) -> FlowResult:
        self._opts["price_type"] = PRICE_SPOT
        return self.async_show_menu(step_id="spot", menu_options=["spot_final_yes", "spot_final_no"])

    async def async_step_spot_final_yes(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            state = self.hass.states.get(user_input["price_entity"])
            if not parse_prices(state):
                errors["price_entity"] = "invalid_price_sensor"
            else:
                self._opts.update(user_input, spot_final=True)
                items = price_list_attribute(state) or []
                with_tariff = sum(1 for i in items if str(i.get("tariff", "")).upper() in ("VT", "NT"))
                if items and with_tariff >= 0.8 * len(items):
                    # VT/NT comes with the data – no need to ask
                    self._opts.update(tariff_source=TARIFF_DATA, hdo_entity=None, vt_windows="")
                    return await self._after_prices()
                return await self.async_step_tariff_source()
        return self.async_show_form(
            step_id="spot_final_yes",
            data_schema=vol.Schema({_req("price_entity", self._opts, vol.UNDEFINED): _entity("sensor")}),
            errors=errors,
        )

    async def async_step_spot_final_no(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not parse_prices(self.hass.states.get(user_input["price_entity"])):
                errors["price_entity"] = "invalid_price_sensor"
            else:
                self._opts.update(user_input, spot_final=False)
                return await self.async_step_tariff_source()
        o = self._opts
        return self.async_show_form(
            step_id="spot_final_no",
            data_schema=vol.Schema(
                {
                    _req("price_entity", o, vol.UNDEFINED): _entity("sensor"),
                    _req("markup", o, 0.0): _money(),
                    _req("distribution_vt", o, 0.0): _money(),
                    _req("distribution_nt", o, 0.0): _money(),
                    _req("vat", o, DEFAULT_VAT): VAT_SELECTOR,
                }
            ),
            errors=errors,
        )

    async def async_step_fixed2(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._opts.update(user_input, price_type=PRICE_FIXED2)
            return await self.async_step_tariff_source()
        o = self._opts
        return self.async_show_form(
            step_id="fixed2",
            data_schema=vol.Schema(
                {
                    _req("energy_vt", o, 0.0): _money(),
                    _req("energy_nt", o, 0.0): _money(),
                    _req("distribution_vt", o, 0.0): _money(),
                    _req("distribution_nt", o, 0.0): _money(),
                    _req("vat", o, DEFAULT_VAT): VAT_SELECTOR,
                }
            ),
        )

    async def async_step_fixed1(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._opts.update(
                price_type=PRICE_FIXED1,
                energy_vt=user_input["energy"], energy_nt=user_input["energy"],
                distribution_vt=user_input["distribution"], distribution_nt=user_input["distribution"],
                vat=user_input["vat"],
                tariff_source=TARIFF_NONE, hdo_entity=None, vt_windows="",
            )
            return await self._after_prices()
        o = self._opts
        return self.async_show_form(
            step_id="fixed1",
            data_schema=vol.Schema(
                {
                    vol.Required("energy", default=o.get("energy_vt") or 0.0): _money(),
                    vol.Required("distribution", default=o.get("distribution_vt") or 0.0): _money(),
                    _req("vat", o, DEFAULT_VAT): VAT_SELECTOR,
                }
            ),
        )

    async def _after_prices(self) -> FlowResult:
        if self._is_options:
            return await self.async_step_summary()
        return await self.async_step_cars()

    # ------------------------------------------------------------ VT / NT

    async def async_step_tariff_source(self, user_input=None) -> FlowResult:
        return self.async_show_menu(
            step_id="tariff_source", menu_options=["tariff_cez", "tariff_sensor", "tariff_manual"]
        )

    async def async_step_tariff_cez(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            state = self.hass.states.get(user_input["hdo_entity"])
            if state is None or not _find_cez_signals(dict(state.attributes)):
                errors["hdo_entity"] = "invalid_cez"
            else:
                self._opts.update(user_input, tariff_source=TARIFF_CEZ, vt_windows="")
                return await self._after_tariff()
        return self.async_show_form(
            step_id="tariff_cez",
            data_schema=vol.Schema({_req("hdo_entity", self._opts, vol.UNDEFINED): _entity("sensor")}),
            errors=errors,
        )

    async def async_step_tariff_sensor(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            state = self.hass.states.get(user_input["hdo_entity"])
            usable = state is not None and (
                state.domain == "binary_sensor" or bool(parse_hdo_windows(state))
            )
            if not usable:
                errors["hdo_entity"] = "invalid_hdo"
            else:
                self._opts.update(user_input, tariff_source=TARIFF_SENSOR)
                self._opts.setdefault("vt_windows", "")
                return await self._after_tariff()
        o = self._opts
        return self.async_show_form(
            step_id="tariff_sensor",
            data_schema=vol.Schema(
                {
                    _req("hdo_entity", o, vol.UNDEFINED): _entity(["binary_sensor", "sensor"]),
                    vol.Optional("vt_windows", default=o.get("vt_windows") or ""): selector.TextSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_tariff_manual(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                parse_vt_windows(user_input["vt_windows"])
            except ValueError:
                errors["vt_windows"] = "invalid_vt_windows"
            else:
                self._opts.update(user_input, tariff_source=TARIFF_MANUAL, hdo_entity=None)
                return await self._after_tariff()
        return self.async_show_form(
            step_id="tariff_manual",
            data_schema=vol.Schema(
                {vol.Required("vt_windows", default=self._opts.get("vt_windows") or ""): selector.TextSelector()}
            ),
            errors=errors,
        )

    async def _after_tariff(self) -> FlowResult:
        return await self._after_prices()

    # ------------------------------------------------------------ cars

    async def async_step_cars(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._car_count = int(user_input["count"])
            self._opts["cars"] = list(self._opts.get("cars") or [])[: self._car_count]
            self._car_index = 0
            if self._car_count == 0:
                return await self.async_step_summary()
            return await self.async_step_car()
        return self.async_show_form(
            step_id="cars",
            data_schema=vol.Schema(
                {
                    vol.Required("count", default=str(len(self._opts.get("cars") or []))): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[str(i) for i in range(MAX_CARS + 1)],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_car(self, user_input=None) -> FlowResult:
        cars: list[dict[str, Any]] = self._opts.setdefault("cars", [])
        current = cars[self._car_index] if self._car_index < len(cars) else {}
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input["name"].strip()
            others = [c["name"].lower() for i, c in enumerate(cars) if i != self._car_index]
            if not name or name.lower() in others or name.lower() == "other":
                errors["name"] = "invalid_car_name"
            elif user_input.get("soc_entity") and not user_input.get("battery_kwh"):
                errors["battery_kwh"] = "battery_required"
            else:
                car = normalize_car({**current, **user_input, "name": name}, self._car_index)
                if self._car_index < len(cars):
                    cars[self._car_index] = car
                else:
                    cars.append(car)
                self._car_index += 1
                if self._car_index < self._car_count:
                    return await self.async_step_car()
                return await self.async_step_summary()
        c = {**current, **(user_input or {})}
        return self.async_show_form(
            step_id="car",
            description_placeholders={"number": str(self._car_index + 1), "count": str(self._car_count)},
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=c.get("name") or f"Auto {self._car_index + 1}"): selector.TextSelector(),
                    _opt("soc_entity", c): _entity("sensor"),
                    vol.Optional("battery_kwh", default=c.get("battery_kwh") or 0.0): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0, max=250, step=0.1, unit_of_measurement="kWh", mode=selector.NumberSelectorMode.BOX)
                    ),
                    vol.Optional("efficiency", default=c.get("efficiency") or DEFAULT_EFFICIENCY): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=50, max=100, step=1, unit_of_measurement="%", mode=selector.NumberSelectorMode.BOX)
                    ),
                    _opt("plug_entity", c): _entity(["binary_sensor", "sensor"]),
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------ summary

    def _summary(self) -> dict[str, str]:
        o = normalize_options(self._opts)
        now = dt_util.now()
        tariff = build_tariff(self.hass, o, now)
        entity = o["price_entity"]
        if o["price_type"] == PRICE_SPOT and not entity:
            from .scheduler import AUTO_PRICE_ENTITIES  # noqa: PLC0415

            entity = next((e for e in AUTO_PRICE_ENTITIES if self.hass.states.get(e)), None)
        slots = build_slots(self.hass, o, tariff, now, now + timedelta(hours=24), entity)
        lines = []
        if o["price_type"] == PRICE_SPOT:
            cur = slot_at(slots, now)
            today = [s for s in slots if s.start.date() == now.date()]
            if cur:
                lines.append(f"Cena teď: **{_fmt(cur.price)} Kč/kWh** s DPH")
            if today:
                lines.append(
                    f"Dnes: {_fmt(min(s.price for s in today))} – {_fmt(max(s.price for s in today))} Kč/kWh"
                )
            if not slots:
                lines.append("⚠ Senzor ceny teď nemá žádné ceny")
        elif o["price_type"] == PRICE_FIXED2:
            f = 1 + o["vat"] / 100
            lines.append(f"VT: **{_fmt((o['energy_vt'] + o['distribution_vt']) * f)} Kč/kWh** s DPH")
            lines.append(f"NT: **{_fmt((o['energy_nt'] + o['distribution_nt']) * f)} Kč/kWh** s DPH")
        else:
            f = 1 + o["vat"] / 100
            lines.append(f"Cena: **{_fmt((o['energy_vt'] + o['distribution_vt']) * f)} Kč/kWh** s DPH")

        source = {
            TARIFF_DATA: "z dat cenového senzoru",
            TARIFF_CEZ: "ČEZ Distribuce",
            TARIFF_SENSOR: "HDO senzor",
            TARIFF_MANUAL: "ručně zadané časy",
            TARIFF_NONE: "jednotarif",
        }[o["tariff_source"]]
        if o["tariff_source"] == TARIFF_NONE:
            tariff_text = "Jednotarif – bez VT/NT"
        elif o["tariff_source"] == TARIFF_DATA:
            nt = [s for s in slots if s.low_tariff and s.start.date() == now.date()]
            tariff_text = f"VT/NT: {source} ({len(nt) // 4} h NT dnes)"
        else:
            tariff_text = f"VT/NT: {source}\nNT dnes: {nt_windows_text(tariff, now)}"

        cars = o["cars"]
        if cars:
            car_lines = []
            for car in cars:
                bits = []
                if car["soc_entity"]:
                    st = self.hass.states.get(car["soc_entity"])
                    bits.append(f"baterie {st.state} %" if st else "baterie ?")
                if car["battery_kwh"]:
                    bits.append(f"{car['battery_kwh']:g} kWh")
                bits.append("rozpoznání ✓" if car["plug_entity"] else "bez rozpoznání")
                car_lines.append(f"• {car['name']}: " + ", ".join(bits))
            cars_text = "Auta:\n" + "\n".join(car_lines)
        else:
            cars_text = "Auta: žádná (cíl jen v hodinách nebo kWh)"
        return {"prices": "\n".join(lines), "tariff": tariff_text, "cars": cars_text}

    async def async_step_summary(self, user_input=None) -> FlowResult:
        if user_input is not None:
            return self._finish()
        return self.async_show_form(
            step_id="summary", data_schema=vol.Schema({}), description_placeholders=self._summary()
        )


class EcoVolterConfigFlow(_Wizard, config_entries.ConfigFlow, domain=DOMAIN):
    """Handle EcoVolter configuration."""

    VERSION = 2

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
                return await self.async_step_tariff_type()

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
        return self.async_create_entry(
            title=self._title, data=self._data, options=normalize_options(self._opts)
        )


class EcoVolterOptionsFlow(_Wizard, config_entries.OptionsFlow):
    """Menu: prices · VT/NT · cars · refresh interval."""

    _is_options = True

    async def async_step_init(self, user_input=None) -> FlowResult:
        self._opts = normalize_options(dict(self.config_entry.options))
        menu = ["tariff_type", "tariff_source", "cars", "interval"]
        if self._opts["price_type"] == PRICE_FIXED1:
            menu.remove("tariff_source")  # single rate has no VT/NT
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_interval(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._opts.update(user_input)
            return self._finish()
        return self.async_show_form(
            step_id="interval",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self._opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
                }
            ),
        )

    def _finish(self) -> FlowResult:
        return self.async_create_entry(data=normalize_options(self._opts))
