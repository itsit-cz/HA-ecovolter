"""Scheduler options: canonical format, migration from older versions."""

from __future__ import annotations

from typing import Any
import uuid

PRICE_SPOT = "spot"
PRICE_FIXED2 = "fixed2"  # two-rate tariff (VT / NT)
PRICE_FIXED1 = "fixed1"  # single rate

TARIFF_DATA = "data"  # VT/NT comes with the final-price sensor
TARIFF_CEZ = "cez"
TARIFF_SENSOR = "sensor"
TARIFF_MANUAL = "manual"
TARIFF_NONE = "none"

MAX_CARS = 3
DEFAULT_VAT = 21.0
DEFAULT_EFFICIENCY = 90.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def new_car_id() -> str:
    return uuid.uuid4().hex[:8]


def normalize_car(car: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "id": str(car.get("id") or new_car_id()),
        "name": str(car.get("name") or f"Auto {index + 1}").strip()[:30],
        "soc_entity": car.get("soc_entity") or None,
        "battery_kwh": _num(car.get("battery_kwh")),
        "efficiency": min(100.0, max(50.0, _num(car.get("efficiency"), DEFAULT_EFFICIENCY))),
        "plug_entity": car.get("plug_entity") or None,
    }


def normalize_options(opts: dict[str, Any]) -> dict[str, Any]:
    """Return options in the current format; converts settings of v0.4.0-beta.6 and older."""
    o = dict(opts or {})
    price_type = o.get("price_type")
    migrated_vat: float | None = None

    if price_type in (None, "sensor"):  # beta ≤6: spot / price sensor
        price_type = PRICE_SPOT
        # old behaviour: final-price list sensor as-is, spot sensor + distribution
        # (distribution entered incl. VAT) -> keep it with "auto" and VAT 0
        o.setdefault("spot_final", None)
        migrated_vat = 0.0
    elif price_type == "fixed":  # beta 6: fixed two-rate, prices incl. VAT
        price_type = PRICE_FIXED2
        migrated_vat = 0.0
    o["price_type"] = price_type

    if "vat" not in o:
        o["vat"] = migrated_vat if migrated_vat is not None else DEFAULT_VAT
    o["vat"] = _num(o["vat"], DEFAULT_VAT)
    for key in ("markup", "distribution_vt", "distribution_nt", "energy_vt", "energy_nt"):
        o[key] = _num(o.get(key))
    if price_type == PRICE_FIXED1:
        o["energy_nt"] = o["energy_vt"]
        o["distribution_nt"] = o["distribution_vt"]
    o.setdefault("spot_final", None)
    o["price_entity"] = o.get("price_entity") or None

    # tariff source
    o["hdo_entity"] = o.get("hdo_entity") or None
    o["vt_windows"] = o.get("vt_windows") or ""
    if "tariff_source" not in o:
        if o["hdo_entity"]:
            o["tariff_source"] = TARIFF_SENSOR
        elif o["vt_windows"]:
            o["tariff_source"] = TARIFF_MANUAL
        else:
            o["tariff_source"] = TARIFF_DATA if price_type == PRICE_SPOT else TARIFF_NONE
    if price_type == PRICE_FIXED1:
        o["tariff_source"] = TARIFF_NONE

    # cars
    cars = o.get("cars")
    if cars is None:
        cars = []
        if o.get("soc_entity") or _num(o.get("battery_kwh")):  # beta 6: one car
            cars.append(
                {
                    "name": "Auto",
                    "soc_entity": o.get("soc_entity"),
                    "battery_kwh": o.get("battery_kwh"),
                    "efficiency": o.get("charging_efficiency", DEFAULT_EFFICIENCY),
                }
            )
    o["cars"] = [normalize_car(c, i) for i, c in enumerate(cars[:MAX_CARS])]
    for old in ("soc_entity", "battery_kwh", "charging_efficiency"):
        o.pop(old, None)
    return o


def vat_factor(o: dict[str, Any]) -> float:
    return 1 + _num(o.get("vat"), 0.0) / 100
