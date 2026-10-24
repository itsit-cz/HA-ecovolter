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
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "tariff_source"})
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "tariff_manual"})
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"vt_windows": "ráno"})
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


async def test_target_reached_stays_done_after_replug(hass: HomeAssistant, freezer) -> None:
    tz = dt_util.get_default_time_zone()
    start = datetime(2026, 10, 24, 22, 0, tzinfo=tz)
    freezer.move_to(start)
    hass.states.async_set(SPOT, "1", _prices_state(start, [1] * 12).attributes)
    entry, status, settings, pm, ids, patches = await _setup(hass)
    coord = entry.runtime_data
    sched = coord.scheduler

    async def poll(seconds=2):
        freezer.tick(seconds)
        await coord.async_refresh()
        await hass.async_block_till_done()

    try:
        sched.set_option("ready_by", "06:00")
        sched.set_option("target_hours", 0.25)  # 15 min
        sched.set_option("mode", "cheapest")
        await hass.async_block_till_done()
        assert settings["isChargingEnable"] is True
        status.update(isCharging=True, actualPower=11.0)
        for _ in range(16):
            await poll(60)
        assert sched.finished and sched.reason == "target_reached"
        assert settings["isChargingEnable"] is False
        status.update(isCharging=False, actualPower=0)

        # unplug, charger re-enables itself on the next plug-in -> scheduler turns it off again
        status["isVehicleConnected"] = False
        await poll(60)
        status["isVehicleConnected"] = True
        settings["isChargingEnable"] = True
        await poll(2)
        assert settings["isChargingEnable"] is False

        # deadline passes -> still done, no new plan on its own
        freezer.move_to(start.replace(day=25, hour=8))
        await poll(2)
        assert sched.finished and sched.charge_now is False
        assert hass.states.get(ids["charging_plan"]).attributes["finished"] is True

        # "charge again" starts a new plan
        await hass.services.async_call("button", "press", {"entity_id": ids["charge_again"]}, blocking=True)
        assert not sched.finished and sched.plan.needed_seconds == 900

        # finish again, then the same target set by an automation re-arms too
        sched.finished = True
        sched.set_option("target_hours", 0.25)
        assert not sched.finished and sched.delivered_seconds == 0
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        for p in patches:
            p.stop()



# ---------------------------------------------- fixed tariff, HDO, SoC, control


def test_fixed_tariff_with_hdo_windows() -> None:
    from custom_components.ecovolter.scheduler import TariffModel, fixed_tariff_slots, parse_hdo_windows

    tz = dt_util.get_default_time_zone()
    day = datetime(2026, 10, 24, 0, 0, tzinfo=tz)
    hdo = State(
        "sensor.cez_hdo",
        "x",
        {
            "next_windows": [
                {"start": day.replace(hour=0).isoformat(), "end": day.replace(hour=8).isoformat()},
                {"start": day.replace(hour=9).isoformat(), "end": day.replace(hour=16).isoformat()},
                {"start": day.replace(hour=17).isoformat(), "end": (day + timedelta(days=1)).isoformat()},
            ]
        },
    )
    tariff = TariffModel([], parse_hdo_windows(hdo))
    slots = fixed_tariff_slots(day, day + timedelta(days=2), tariff, 4.0, 2.0, 1.5, 0.3)
    by = {s.start: s for s in slots}
    assert by[day.replace(hour=8)].price == pytest.approx(5.5)  # VT 4 + 1.5
    assert by[day.replace(hour=10)].price == pytest.approx(2.3)  # NT 2 + 0.3
    # beyond the known windows the last day's pattern repeats
    assert not by[day.replace(day=25, hour=8, minute=30)].low_tariff
    assert by[day.replace(day=25, hour=12)].low_tariff
    # binary HDO sensor decides "now"
    now = day.replace(hour=8, minute=5)
    assert TariffModel([], [], hdo_now=True, now=now)(now.replace(minute=0))


async def test_fixed_tariff_entry_and_soc_target(hass: HomeAssistant, freezer) -> None:
    tz = dt_util.get_default_time_zone()
    start = datetime(2026, 10, 24, 20, 0, tzinfo=tz)
    freezer.move_to(start)
    hass.states.async_set("sensor.auto_baterie", "60", {"device_class": "battery", "unit_of_measurement": "%"})
    entry, status, settings, pm, ids, patches = await _setup(
        hass,
        options={
            "price_type": "fixed", "energy_vt": 4.0, "energy_nt": 2.0,
            "distribution_vt": 1.5, "distribution_nt": 0.3, "vt_windows": "20:00-22:00",
            "soc_entity": "sensor.auto_baterie", "battery_kwh": 50, "charging_efficiency": 90,
        },
    )
    sched = entry.runtime_data.scheduler
    try:
        assert sched.current_price == pytest.approx(5.5)
        await hass.services.async_call("number", "set_value", {"entity_id": ids["target_soc"], "value": 80}, blocking=True)
        await hass.services.async_call("select", "select_option", {"entity_id": ids["target_type"], "option": "soc"}, blocking=True)
        await hass.services.async_call("select", "select_option", {"entity_id": ids["charging_mode"], "option": "cheapest"}, blocking=True)
        # 20 % of 50 kWh / 0.9 = 11.1 kWh at 11.04 kW ≈ 1 h, only NT slots (from 22:00)
        assert sched.needed_kwh_soc() == pytest.approx(11.11, rel=0.01)
        assert min(sched.plan.selected) == start.replace(hour=22)
        assert settings["isChargingEnable"] is False
        attrs = hass.states.get(ids["charging_plan"]).attributes
        assert attrs["soc"] == 60 and attrs["target_soc"] == 80

        # SoC reaches the target earlier than planned -> stop right away, done
        freezer.move_to(start.replace(hour=22, minute=1))
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert settings["isChargingEnable"] is True
        hass.states.async_set("sensor.auto_baterie", "80", {"device_class": "battery"})
        freezer.tick(2)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert sched.finished and settings["isChargingEnable"] is False

        # no SoC sensor value -> do not charge, report it
        hass.states.async_set("sensor.auto_baterie", "unavailable")
        sched.rearm()
        assert sched.reason == "no_soc" and not sched.charge_now
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        for p in patches:
            p.stop()


async def test_plan_change_overrides_manual_and_rate_limit(hass: HomeAssistant, freezer) -> None:
    tz = dt_util.get_default_time_zone()
    start = datetime(2026, 10, 24, 20, 0, tzinfo=tz)
    freezer.move_to(start + timedelta(minutes=1))
    hass.states.async_set(SPOT, "5", _prices_state(start, [1, 9, 9, 9, 9, 9]).attributes)
    entry, status, settings, pm, ids, patches = await _setup(hass)
    sched = entry.runtime_data.scheduler
    try:
        sched.set_option("ready_by", "02:00")
        sched.set_option("target_hours", 1)
        sched.set_option("mode", "cheapest")
        await hass.async_block_till_done()
        assert settings["isChargingEnable"] is True  # 20:00 is the cheap hour
        # user switches charging off by hand -> respected
        await hass.services.async_call("switch", "turn_off", {"entity_id": ids["charging_enabled"]}, blocking=True)
        await hass.async_block_till_done()
        assert settings["isChargingEnable"] is False
        # user changes the plan (deadline) -> plan takes control immediately, no 30 s wait
        await hass.services.async_call("time", "set_value", {"entity_id": ids["ready_by"], "time": "03:00:00"}, blocking=True)
        await hass.async_block_till_done()
        assert settings["isChargingEnable"] is True
        # plan change that stops charging also applies immediately
        await hass.services.async_call("number", "set_value", {"entity_id": ids["max_price"], "value": 0.5}, blocking=True)
        await hass.async_block_till_done()
        assert settings["isChargingEnable"] is False
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        for p in patches:
            p.stop()


async def _start_flow(hass):
    from homeassistant import config_entries

    hass.config.components.update({"frontend", "http"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    return await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "10.0.0.9", CONF_SECRET: "s"})


FLOW_PATCHES = (
    lambda: patch.object(EcoVolterApi, "async_get_diagnostic", return_value={"serialNumber": "XYZ"}),
    lambda: patch.object(EcoVolterApi, "async_get_status", return_value={}),
    lambda: patch("custom_components.ecovolter.async_setup_entry", return_value=True),
    lambda: patch("custom_components.ecovolter.async_setup", return_value=True),
)


async def test_wizard_spot_final_with_tariff_in_data(hass: HomeAssistant, freezer) -> None:
    tz = dt_util.get_default_time_zone()
    start = datetime(2026, 10, 24, 20, 0, tzinfo=tz)
    freezer.move_to(start)
    st = _final_state(start, [5.6, 4.9, 4.3, 4.7])
    hass.states.async_set(st.entity_id, st.state, st.attributes)
    hass.states.async_set("sensor.bila_baterie", "62")
    with FLOW_PATCHES[0](), FLOW_PATCHES[1](), FLOW_PATCHES[2](), FLOW_PATCHES[3]():
        result = await _start_flow(hass)
        assert result["type"] == "menu" and result["step_id"] == "tariff_type"
        flow = result["flow_id"]
        result = await hass.config_entries.flow.async_configure(flow, {"next_step_id": "spot"})
        assert result["step_id"] == "spot"
        result = await hass.config_entries.flow.async_configure(flow, {"next_step_id": "spot_final_yes"})
        result = await hass.config_entries.flow.async_configure(flow, {"price_entity": "sensor.neexistuje"})
        assert result["errors"] == {"price_entity": "invalid_price_sensor"}
        result = await hass.config_entries.flow.async_configure(flow, {"price_entity": st.entity_id})
        # tariff is in the data -> VT/NT step skipped
        assert result["step_id"] == "cars"
        result = await hass.config_entries.flow.async_configure(flow, {"count": "2"})
        assert result["step_id"] == "car"
        result = await hass.config_entries.flow.async_configure(
            flow, {"name": "Bílá", "soc_entity": "sensor.bila_baterie", "battery_kwh": 77, "efficiency": 90, "plug_entity": "binary_sensor.bila_kabel"}
        )
        result = await hass.config_entries.flow.async_configure(flow, {"name": "bílá", "battery_kwh": 0, "efficiency": 90})
        assert result["errors"] == {"name": "invalid_car_name"}
        result = await hass.config_entries.flow.async_configure(flow, {"name": "Modrá", "battery_kwh": 0, "efficiency": 90})
        assert result["step_id"] == "summary"
        text = "\n".join(result["description_placeholders"].values())
        assert "5,60 Kč/kWh" in text and "z dat cenového senzoru" in text and "Bílá: baterie 62 %" in text
        result = await hass.config_entries.flow.async_configure(flow, {})
        assert result["type"] == "create_entry"
        o = result["options"]
        assert o["price_type"] == "spot" and o["spot_final"] is True and o["tariff_source"] == "data"
        assert [c["name"] for c in o["cars"]] == ["Bílá", "Modrá"]
        assert o["cars"][0]["plug_entity"] == "binary_sensor.bila_kabel"


async def test_wizard_spot_without_final_price_and_cez(hass: HomeAssistant, freezer) -> None:
    tz = dt_util.get_default_time_zone()
    start = datetime(2026, 10, 24, 10, 0, tzinfo=tz)
    freezer.move_to(start)
    hass.states.async_set(SPOT, "2", _prices_state(start, [2.0] * 4).attributes)
    casy = "00:00-08:00; 09:00-12:00; 13:00-15:00; 16:00-19:00; 20:00-24:00"
    hass.states.async_set(
        "sensor.cez_hdo_raw", "ok",
        {"raw_json": {"data": {"data": {"signals": [{"signal": "EVV2", "datum": "24.10.2026", "casy": casy}]}}}},
    )
    hass.states.async_set("sensor.neni_cez", "on")
    with FLOW_PATCHES[0](), FLOW_PATCHES[1](), FLOW_PATCHES[2](), FLOW_PATCHES[3]():
        flow = (await _start_flow(hass))["flow_id"]
        await hass.config_entries.flow.async_configure(flow, {"next_step_id": "spot"})
        result = await hass.config_entries.flow.async_configure(flow, {"next_step_id": "spot_final_no"})
        result = await hass.config_entries.flow.async_configure(
            flow, {"price_entity": SPOT, "markup": 0.5, "distribution_vt": 1.5, "distribution_nt": 0.5, "vat": 21}
        )
        assert result["type"] == "menu" and result["step_id"] == "tariff_source"
        result = await hass.config_entries.flow.async_configure(flow, {"next_step_id": "tariff_cez"})
        result = await hass.config_entries.flow.async_configure(flow, {"hdo_entity": "sensor.neni_cez"})
        assert result["errors"] == {"hdo_entity": "invalid_cez"}
        result = await hass.config_entries.flow.async_configure(flow, {"hdo_entity": "sensor.cez_hdo_raw"})
        result = await hass.config_entries.flow.async_configure(flow, {"count": "0"})
        assert result["step_id"] == "summary"
        text = "\n".join(result["description_placeholders"].values())
        # 10:00 is NT: (2 + 0.5 + 0.5) * 1.21 = 3.63
        assert "3,63 Kč/kWh" in text
        assert "NT dnes: 00:00–08:00, 09:00–12:00, 13:00–15:00, 16:00–19:00, 20:00–24:00" in text
        result = await hass.config_entries.flow.async_configure(flow, {})
        o = result["options"]
        assert o["spot_final"] is False and o["tariff_source"] == "cez" and o["vat"] == 21


async def test_wizard_fixed_tariffs(hass: HomeAssistant) -> None:
    with FLOW_PATCHES[0](), FLOW_PATCHES[1](), FLOW_PATCHES[2](), FLOW_PATCHES[3]():
        flow = (await _start_flow(hass))["flow_id"]
        result = await hass.config_entries.flow.async_configure(flow, {"next_step_id": "fixed1"})
        result = await hass.config_entries.flow.async_configure(flow, {"energy": 3, "distribution": 1, "vat": 21})
        assert result["step_id"] == "cars"  # single rate: no VT/NT step
        result = await hass.config_entries.flow.async_configure(flow, {"count": "0"})
        assert "4,84 Kč/kWh" in result["description_placeholders"]["prices"]
        result = await hass.config_entries.flow.async_configure(flow, {})
        assert result["options"]["price_type"] == "fixed1" and result["options"]["tariff_source"] == "none"
        await hass.config_entries.async_remove(result["result"].entry_id)

        flow = (await _start_flow(hass))["flow_id"]
        await hass.config_entries.flow.async_configure(flow, {"next_step_id": "fixed2"})
        result = await hass.config_entries.flow.async_configure(
            flow, {"energy_vt": 4, "energy_nt": 2, "distribution_vt": 1.5, "distribution_nt": 0.3, "vat": 21}
        )
        assert result["step_id"] == "tariff_source"
        await hass.config_entries.flow.async_configure(flow, {"next_step_id": "tariff_manual"})
        result = await hass.config_entries.flow.async_configure(flow, {"vt_windows": "8:00-9:00"})
        result = await hass.config_entries.flow.async_configure(flow, {"count": "0"})
        prices = result["description_placeholders"]["prices"]
        assert "VT: **6,66 Kč/kWh**" in prices and "NT: **2,78 Kč/kWh**" in prices
        assert "NT dnes: 00:00–08:00, 09:00–24:00" in result["description_placeholders"]["tariff"]


def test_migration_of_beta6_options() -> None:
    from custom_components.ecovolter.options import normalize_options

    o = normalize_options(
        {"scan_interval": 2, "price_type": "sensor", "distribution_vt": 0, "distribution_nt": 0,
         "hdo_entity": "sensor.cez_hdo_raw", "soc_entity": "sensor.bila", "battery_kwh": 77, "charging_efficiency": 90}
    )
    assert o["price_type"] == "spot" and o["spot_final"] is None and o["vat"] == 0
    assert o["tariff_source"] == "sensor" and o["scan_interval"] == 2
    assert len(o["cars"]) == 1 and o["cars"][0]["soc_entity"] == "sensor.bila" and o["cars"][0]["battery_kwh"] == 77
    assert "soc_entity" not in o
    assert normalize_options({"price_type": "fixed"})["price_type"] == "fixed2"
    assert normalize_options({})["cars"] == []


async def test_multiple_cars_detection_and_targets(hass: HomeAssistant, freezer) -> None:
    tz = dt_util.get_default_time_zone()
    start = datetime(2026, 10, 24, 20, 0, tzinfo=tz)
    freezer.move_to(start)
    hass.states.async_set(SPOT, "1", _prices_state(start, [1] * 12).attributes)
    hass.states.async_set("sensor.bila", "50")
    hass.states.async_set("sensor.modra", "30")
    hass.states.async_set("binary_sensor.bila_kabel", "off")
    hass.states.async_set("sensor.modra_nabijeni", "disconnected")
    entry, status, settings, pm, ids, patches = await _setup(
        hass,
        options={
            "price_type": "spot", "spot_final": True,
            "cars": [
                {"id": "b", "name": "Bílá", "soc_entity": "sensor.bila", "battery_kwh": 50, "plug_entity": "binary_sensor.bila_kabel"},
                {"id": "m", "name": "Modrá", "soc_entity": "sensor.modra", "battery_kwh": 60, "plug_entity": "sensor.modra_nabijeni"},
            ],
        },
    )
    coord = entry.runtime_data
    sched = coord.scheduler
    car_select = ids["car"]

    async def poll(sec=2):
        freezer.tick(sec)
        await coord.async_refresh()
        await hass.async_block_till_done()

    try:
        assert hass.states.get(car_select).attributes["options"] == ["Bílá", "Modrá", "other"]
        assert hass.states.get(car_select).state == "Bílá"
        # per-car targets
        await hass.services.async_call("number", "set_value", {"entity_id": ids["target_soc"], "value": 70}, blocking=True)
        await hass.services.async_call("select", "select_option", {"entity_id": car_select, "option": "Modrá"}, blocking=True)
        await hass.services.async_call("number", "set_value", {"entity_id": ids["target_soc"], "value": 90}, blocking=True)
        assert sched.target_soc == 90
        await hass.services.async_call("select", "select_option", {"entity_id": car_select, "option": "Bílá"}, blocking=True)
        assert sched.target_soc == 70
        assert float(hass.states.get(ids["target_soc"]).state) == 70

        # Modrá gets plugged in: its own sensor says "charging" -> detected
        status["isVehicleConnected"] = False
        await poll()
        status["isVehicleConnected"] = True
        await poll()
        hass.states.async_set("sensor.modra_nabijeni", "Charging")
        await poll()
        assert hass.states.get(car_select).state == "Modrá"
        assert sched.needed_kwh_soc() == pytest.approx((90 - 30) / 100 * 60 / 0.9)

        # next session: no car reports the cable within 2 min -> ask in the card
        hass.states.async_set("sensor.modra_nabijeni", "disconnected")
        status["isVehicleConnected"] = False
        await poll()
        status["isVehicleConnected"] = True
        await poll()
        await poll(130)
        assert sched.car_ambiguous is True
        assert hass.states.get(car_select).attributes["ambiguous"] is True
        await hass.services.async_call("select", "select_option", {"entity_id": car_select, "option": "Bílá"}, blocking=True)
        assert sched.car_ambiguous is False

        # "other" car: % target not possible
        await hass.services.async_call("select", "select_option", {"entity_id": car_select, "option": "other"}, blocking=True)
        sched.set_option("target_type", "soc")
        sched.set_option("mode", "cheapest")
        assert sched.reason == "no_soc"
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        for p in patches:
            p.stop()


def test_cez_raw_hdo_schedule() -> None:
    from custom_components.ecovolter.scheduler import TariffModel, parse_hdo_windows

    casy = "00:00-08:00;   09:00-12:00;   13:00-15:00;   16:00-19:00;   20:00-24:00"
    days = ["24.10.2026", "25.10.2026", "26.10.2026"]
    state = State(
        "sensor.cez_hdo_raw_data_8452_evv2",
        "ok",
        {
            "raw_json": {
                "timestamp": "2026-10-24T04:58:28+02:00",
                "data": {"data": {"signals": [{"signal": "EVV2", "den": "x", "datum": d, "casy": casy} for d in days], "amm": False}},
            },
            "friendly_name": "ČEZ HDO (EVV2) Surová data",
        },
    )
    windows = parse_hdo_windows(state)
    tz = dt_util.get_default_time_zone()
    d = datetime(2026, 10, 24, tzinfo=tz)
    # 20:00-24:00 and next day's 00:00-08:00 are merged
    assert (d.replace(hour=20), d.replace(day=25, hour=8)) in windows
    assert windows[0] == (d, d.replace(hour=8))
    tariff = TariffModel([], windows)
    nt = lambda h, m=0, day=24: tariff(d.replace(day=day, hour=h, minute=m))  # noqa: E731
    assert nt(13, 30) and nt(23) and nt(2, day=25)
    assert not nt(8, 15) and not nt(12, 30) and not nt(15, 45) and not nt(19, 30)
    # after the published days the last day's pattern repeats
    assert not nt(8, 30, day=28) and nt(10, day=28)
