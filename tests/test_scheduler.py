"""Tests for the EcoVolter charging scheduler."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ecovolter.api import EcoVolterApi
from custom_components.ecovolter.const import CONF_SECRET, DOMAIN
from custom_components.ecovolter.scheduler import (
    build_plan,
    is_vt,
    next_deadline,
    parse_prices,
    parse_vt_windows,
)

SPOT = "sensor.current_spot_electricity_price_15min"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def _prices_state(start: datetime, prices: list[float], step_min: int = 60, unit="CZK/kWh"):
    attrs = {"unit_of_measurement": unit, "friendly_name": "Spot"}
    for i, price in enumerate(prices):
        attrs[(start + timedelta(minutes=step_min * i)).isoformat()] = price
    return State(SPOT, str(prices[0]), attrs)


# ------------------------------------------------------------- pure logic


def test_vt_windows_parse_and_match() -> None:
    windows = parse_vt_windows("8:00-9:00, 22:30-0:30;12-13")
    tz = dt_util.get_default_time_zone()
    day = datetime(2026, 10, 24, tzinfo=tz)
    assert is_vt(day.replace(hour=8, minute=30), windows)
    assert not is_vt(day.replace(hour=9), windows)
    assert is_vt(day.replace(hour=23), windows)  # crosses midnight
    assert is_vt(day.replace(hour=0, minute=15), windows)
    assert is_vt(day.replace(hour=12, minute=59), windows)
    with pytest.raises(ValueError):
        parse_vt_windows("ráno")


def test_parse_prices_units_and_distribution() -> None:
    tz = dt_util.get_default_time_zone()
    start = datetime(2026, 10, 24, 7, tzinfo=tz)
    state = _prices_state(start, [3000, 1000, 2000], unit="CZK/MWh")
    slots = parse_prices(
        state, dist_vt=2.0, dist_nt=0.5, vt_windows=parse_vt_windows("8:00-9:00")
    )
    assert [round(s.spot, 3) for s in slots] == [3.0, 1.0, 2.0]
    assert [s.low_tariff for s in slots] == [True, False, True]
    assert [round(s.price, 3) for s in slots] == [3.5, 3.0, 2.5]
    assert slots[-1].end - slots[-1].start == timedelta(hours=1)


def test_cheapest_scattered_quarter_hours() -> None:
    tz = dt_util.get_default_time_zone()
    start = datetime(2026, 10, 24, 18, tzinfo=tz)
    # 15-minute prices; the cheap ones are scattered
    prices = [5, 1, 5, 2, 5, 5, 1, 5, 3, 5, 5, 5]
    slots = parse_prices(_prices_state(start, prices, 15))
    now = start + timedelta(minutes=5)  # 10 min left in the first slot
    deadline = start + timedelta(hours=3)
    plan = build_plan(slots, now, deadline, needed_seconds=45 * 60, power_kw=11)
    chosen = sorted(int((s - start).total_seconds() // 900) for s in plan.selected)
    assert chosen == [1, 3, 6]
    assert plan.complete
    assert plan.estimated_cost == pytest.approx(11 * (1 + 2 + 1) * 0.25)


def test_plan_respects_deadline_max_price_and_reports_shortfall() -> None:
    tz = dt_util.get_default_time_zone()
    start = datetime(2026, 10, 24, 0, tzinfo=tz)
    slots = parse_prices(_prices_state(start, [4, 3, 9, 1, 0.5]))
    plan = build_plan(
        slots, start, start + timedelta(hours=3), needed_seconds=3 * 3600,
        power_kw=7, max_price=5,
    )
    # slot 3/4 are after the deadline, slot 2 is above the limit
    assert sorted(plan.selected) == [start, start + timedelta(hours=1)]
    assert not plan.complete
    assert plan.planned_seconds == 2 * 3600


def test_next_deadline() -> None:
    tz = dt_util.get_default_time_zone()
    now = datetime(2026, 10, 24, 6, 59, tzinfo=tz)
    assert next_deadline(now, time(7, 0)).hour == 7
    assert next_deadline(now.replace(hour=7), time(7, 0)).day == 25


# ------------------------------------------------------------- with HA


STATUS = {"isVehicleConnected": True, "isCharging": False, "actualPower": 0}
SETTINGS = {"isChargingEnable": True, "isThreePhaseModeEnable": True, "targetCurrent": 16}


async def _setup(hass: HomeAssistant, options=None):
    hass.config.components.update({"frontend", "http"})
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "10.0.0.5", CONF_SECRET: "s"},
        options=options or {"distribution_vt": 2.0, "distribution_nt": 0.5, "vt_windows": "8:00-9:00"},
        unique_id="abc",
    )
    entry.add_to_hass(hass)
    status = dict(STATUS)
    settings = dict(SETTINGS)
    patches = [
        patch.object(EcoVolterApi, "async_get_status", side_effect=lambda: dict(status)),
        patch.object(EcoVolterApi, "async_get_settings", side_effect=lambda: dict(settings)),
        patch.object(EcoVolterApi, "async_get_diagnostic", return_value={"serialNumber": "abc"}),
    ]
    for p in patches:
        p.start()

    async def fake_patch(values):
        settings.update(values)

    patch_mock = patch.object(EcoVolterApi, "async_patch_settings", side_effect=fake_patch)
    pm = patch_mock.start()
    patches.append(patch_mock)
    with patch("custom_components.ecovolter.add_extra_js_url"):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    ids = {
        e.translation_key: e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    return entry, status, settings, pm, ids, patches


async def test_cheapest_mode_switches_charger(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    tz = dt_util.get_default_time_zone()
    start = datetime(2026, 10, 24, 20, 0, tzinfo=tz)
    freezer.move_to(start + timedelta(minutes=1))
    # 20:00 expensive, 21:00 cheap, 22:00 expensive, 23:00 cheap
    hass.states.async_set(SPOT, "5", _prices_state(start, [5, 1, 6, 2, 7, 7]).attributes)
    entry, status, settings, pm, ids, patches = await _setup(hass)
    coord = entry.runtime_data
    sched = coord.scheduler
    try:
        assert ids["charging_plan"] and ids["scheduled_now"] and ids["ready_by"]

        await hass.services.async_call("time", "set_value", {"entity_id": ids["ready_by"], "time": "06:00"}, blocking=True)
        await hass.services.async_call("number", "set_value", {"entity_id": ids["target_hours"], "value": 2}, blocking=True)
        await hass.services.async_call("select", "select_option", {"entity_id": ids["charging_mode"], "option": "cheapest"}, blocking=True)
        await hass.async_block_till_done()

        # 20:01 – not a selected slot: charging gets disabled
        assert sched.plan.selected == {start + timedelta(hours=1), start + timedelta(hours=3)}
        assert settings["isChargingEnable"] is False
        assert hass.states.get(ids["scheduled_now"]).state == "off"
        plan_state = hass.states.get(ids["charging_plan"])
        assert dt_util.parse_datetime(plan_state.state) == start + timedelta(hours=1)
        assert plan_state.attributes["estimated_cost"] == pytest.approx(11.04 * (1.5 + 2.5), rel=0.01)

        # 21:00 – cheapest slot starts
        freezer.move_to(start + timedelta(hours=1, minutes=1))
        status["isCharging"] = True
        status["actualPower"] = 11.0
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert settings["isChargingEnable"] is True
        assert hass.states.get(ids["scheduled_now"]).state == "on"

        # user stops charging manually -> scheduler keeps hands off in this slot
        await hass.services.async_call("switch", "turn_off", {"entity_id": ids["charging_enabled"]}, blocking=True)
        freezer.tick(40)
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert settings["isChargingEnable"] is False

        # progress is counted while charging
        assert sched.delivered_seconds > 0

        # price limit mode
        await hass.services.async_call("number", "set_value", {"entity_id": ids["max_price"], "value": 3}, blocking=True)
        await hass.services.async_call("select", "select_option", {"entity_id": ids["charging_mode"], "option": "price_limit"}, blocking=True)
        freezer.tick(40)
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert sched.charge_now is True  # 1 + 0.5 <= 3
        assert settings["isChargingEnable"] is True
        assert float(hass.states.get(ids["current_total_price"]).state) == pytest.approx(1.5)

        # manual mode: scheduler does nothing
        await hass.services.async_call("select", "select_option", {"entity_id": ids["charging_mode"], "option": "manual"}, blocking=True)
        calls = pm.await_count
        freezer.move_to(start + timedelta(hours=2, minutes=1))
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert pm.await_count == calls

        # settings survive a reload
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data.scheduler.config["max_price"] == 3
        assert entry.runtime_data.scheduler.config["ready_by"] == "06:00"
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        for p in patches:
            p.stop()


async def test_energy_target_and_options(hass: HomeAssistant, freezer) -> None:
    tz = dt_util.get_default_time_zone()
    start = datetime(2026, 10, 24, 0, 0, tzinfo=tz)
    freezer.move_to(start)
    hass.states.async_set(SPOT, "1", _prices_state(start, [1, 2, 3, 4, 5, 6]).attributes)
    entry, status, settings, pm, ids, patches = await _setup(hass)
    sched = entry.runtime_data.scheduler
    try:
        sched.set_option("target_type", "energy")
        sched.set_option("target_energy", 22.08)  # 2 h at 16 A, 3 phases
        await hass.async_block_till_done()
        assert round(sched.plan.needed_seconds) == 7200

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"scan_interval": 2, "distribution_vt": 2, "distribution_nt": 0.5, "vt_windows": "ráno"},
        )
        assert result["errors"] == {"vt_windows": "invalid_vt_windows"}
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        for p in patches:
            p.stop()


# ------------------------------------------------- final-price list sensor


def _final_state(start: datetime, prices: list[float], tariffs=None, step_min=15):
    items = []
    for i, price in enumerate(prices):
        items.append(
            {
                "start": (start + timedelta(minutes=step_min * i)).isoformat(),
                "price": price,
                "spot": price - 1.3,
                "tariff": (tariffs or ["NT"] * len(prices))[i],
                "regulated": 0.1165,
            }
        )
    return State(
        "sensor.elektrina_vysledna_cena",
        str(prices[0]),
        {"prices": items, "unit_of_measurement": "Kč/kWh", "device_class": "monetary"},
    )


def test_final_price_list_ignores_distribution() -> None:
    tz = dt_util.get_default_time_zone()
    start = datetime(2026, 10, 24, 20, 30, tzinfo=tz)
    state = _final_state(start, [4.9269, 4.3051, 4.7002], ["NT", "VT", "NT"])
    slots = parse_prices(state, dist_vt=2, dist_nt=0.5, vt_windows=parse_vt_windows("20:00-21:00"))
    assert [s.price for s in slots] == [4.9269, 4.3051, 4.7002]
    assert [s.low_tariff for s in slots] == [True, False, True]  # from "tariff", not the windows
    assert slots[0].end - slots[0].start == timedelta(minutes=15)


def test_tomorrow_unknown_waits_for_published_prices() -> None:
    from custom_components.ecovolter.scheduler import extend_with_estimate

    tz = dt_util.get_default_time_zone()
    day = datetime(2026, 10, 24, 0, 0, tzinfo=tz)
    # today's prices, hourly: 4 Kč most of the day, one cheap hour at 10:00
    prices = [4.0] * 24
    prices[10] = 2.0
    slots = parse_prices(_final_state(day, prices, step_min=60))
    now = day.replace(hour=9, minute=30)  # before tomorrow's prices (~14:00)
    deadline = day + timedelta(days=1, hours=7)
    horizon = extend_with_estimate(slots, deadline)
    assert horizon[-1].estimated and horizon[-1].end == deadline
    plan = build_plan(horizon, now, deadline, needed_seconds=3 * 3600, power_kw=11)
    real = sorted(s for s in plan.selected if s < day + timedelta(days=1))
    # only the cheap hour today is used; the rest waits for the night prices
    assert real == [day.replace(hour=10)]
    assert plan.complete
    est = {s.start for s in horizon if s.estimated}
    assert len(plan.selected & est) == 2


async def test_auto_detects_final_price_sensor(hass: HomeAssistant, freezer) -> None:
    tz = dt_util.get_default_time_zone()
    start = datetime(2026, 10, 24, 20, 0, tzinfo=tz)
    freezer.move_to(start)
    st = _final_state(start, [5.6, 4.9, 4.3, 4.7, 3.9, 3.2, 3.0, 3.3])
    hass.states.async_set(st.entity_id, st.state, st.attributes)
    hass.states.async_set(SPOT, "1", _prices_state(start, [1, 1]).attributes)  # must be ignored
    entry, status, settings, pm, ids, patches = await _setup(hass, options={"distribution_vt": 2, "distribution_nt": 2})
    sched = entry.runtime_data.scheduler
    try:
        assert sched.resolve_price_entity() == "sensor.elektrina_vysledna_cena"
        assert sched.current_price == 5.6  # no distribution added
        sched.set_option("ready_by", "21:00")
        sched.set_option("target_hours", 0.5)
        sched.set_option("mode", "cheapest")
        await hass.async_block_till_done()
        assert sorted(sched.plan.selected) == [start + timedelta(minutes=30), start + timedelta(minutes=45)]
        attrs = hass.states.get(ids["charging_plan"]).attributes
        assert attrs["waiting_for_prices"] is False
        assert len(attrs["slots"][0]) == 5
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        for p in patches:
            p.stop()


async def test_ready_day_tomorrow(hass: HomeAssistant, freezer) -> None:
    tz = dt_util.get_default_time_zone()
    start = datetime(2026, 10, 24, 12, 0, tzinfo=tz)
    freezer.move_to(start)
    entry, status, settings, pm, ids, patches = await _setup(hass)
    sched = entry.runtime_data.scheduler
    try:
        await hass.services.async_call("time", "set_value", {"entity_id": ids["ready_by"], "time": "15:00:00"}, blocking=True)
        assert sched.plan.deadline == start.replace(hour=15)
        assert hass.states.get(ids["ready_day"]).state == "today"

        await hass.services.async_call("select", "select_option", {"entity_id": ids["ready_day"], "option": "tomorrow"}, blocking=True)
        assert sched.plan.deadline == start.replace(day=25, hour=15)
        assert hass.states.get(ids["ready_day"]).state == "tomorrow"

        # after midnight the fixed date stays (it does not become "day after")
        freezer.move_to(start.replace(day=25, hour=1))
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert sched.plan.deadline == start.replace(day=25, hour=15)
        assert hass.states.get(ids["ready_day"]).state == "today"

        # changing the time keeps the chosen day
        await hass.services.async_call("time", "set_value", {"entity_id": ids["ready_by"], "time": "16:00:00"}, blocking=True)
        assert sched.plan.deadline == start.replace(day=25, hour=16)

        # once it passes, back to the daily deadline
        freezer.move_to(start.replace(day=25, hour=16, minute=30))
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert sched.config["ready_date"] is None
        assert sched.plan.deadline == start.replace(day=26, hour=16)

        await hass.services.async_call("select", "select_option", {"entity_id": ids["ready_day"], "option": "day_after"}, blocking=True)
        assert sched.plan.deadline == start.replace(day=27, hour=16)
        await hass.services.async_call("select", "select_option", {"entity_id": ids["ready_day"], "option": "today"}, blocking=True)
        assert sched.plan.deadline == start.replace(day=26, hour=16)  # 16:00 today already passed -> nearest
        assert hass.states.get(ids["ready_day"]).state == "tomorrow"
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        for p in patches:
            p.stop()
