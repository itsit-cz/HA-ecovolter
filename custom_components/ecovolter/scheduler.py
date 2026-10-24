"""Price-based charging scheduler for EcoVolter.

The planning part (``parse_prices``, ``build_plan``…) is pure and has no Home
Assistant state, so it can be unit-tested. ``EcoVolterScheduler`` wires it to
Home Assistant: it reads the spot price sensor, keeps track of how much has
already been charged in the current cycle, and switches charging on/off.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta
import logging
import re
import time as monotonic
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from .coordinator import EcoVolterCoordinator

_LOGGER = logging.getLogger(__name__)

MODE_MANUAL = "manual"
MODE_CHEAPEST = "cheapest"
MODE_PRICE_LIMIT = "price_limit"
MODE_LOW_TARIFF = "low_tariff"
MODES = [MODE_MANUAL, MODE_CHEAPEST, MODE_PRICE_LIMIT, MODE_LOW_TARIFF]

TARGET_HOURS = "hours"
TARGET_ENERGY = "energy"
TARGET_TYPES = [TARGET_HOURS, TARGET_ENERGY]

READY_TODAY = "today"  # nearest occurrence of the time (repeats daily)
READY_TOMORROW = "tomorrow"
READY_DAY_AFTER = "day_after"
READY_DAYS = [READY_TODAY, READY_TOMORROW, READY_DAY_AFTER]

STORAGE_VERSION = 1
# Never switch the charger more often than this (except manual commands).
MIN_COMMAND_INTERVAL = 30
# After the car is plugged in, the charger may enable charging on its own for
# the new session. Changes in this window are not treated as manual overrides.
PLUG_IN_GRACE_SECONDS = 90
# Phase voltage used to estimate charging power from current.
PHASE_VOLTAGE = 230
# Price sensors this integration knows how to read, in order of preference.
# "buy" includes the supplier's markup when configured in the spot integration.
AUTO_PRICE_ENTITIES = (
    "sensor.current_buy_electricity_price_15min",
    "sensor.current_buy_electricity_price",
    "sensor.current_spot_electricity_price_15min",
    "sensor.current_spot_electricity_price",
)


# --------------------------------------------------------------- pure logic


@dataclass(frozen=True)
class PriceSlot:
    start: datetime
    end: datetime
    spot: float  # per kWh
    distribution: float  # per kWh
    low_tariff: bool
    # No published price yet (e.g. tomorrow before ~14:00) – price is a guess.
    estimated: bool = False

    @property
    def price(self) -> float:
        return self.spot + self.distribution


@dataclass
class Plan:
    slots: list[PriceSlot] = field(default_factory=list)  # whole horizon
    selected: set[datetime] = field(default_factory=set)  # slot starts
    needed_seconds: float = 0.0
    planned_seconds: float = 0.0
    estimated_cost: float = 0.0
    deadline: datetime | None = None
    prices_until: datetime | None = None  # end of published prices

    @property
    def waiting_for_prices(self) -> bool:
        return any(s.estimated and s.start in self.selected for s in self.slots)

    @property
    def complete(self) -> bool:
        return self.planned_seconds + 1 >= self.needed_seconds


def parse_vt_windows(text: str | None) -> list[tuple[dtime, dtime]]:
    """Parse '08:00-09:00, 15:30-16:30' into a list of (start, end) times."""
    windows: list[tuple[dtime, dtime]] = []
    for part in re.split(r"[,;\n]+", text or ""):
        match = re.fullmatch(
            r"\s*(\d{1,2})(?::(\d{2}))?\s*-\s*(\d{1,2})(?::(\d{2}))?\s*", part
        )
        if not match:
            if part.strip():
                raise ValueError(f"Invalid time window: {part.strip()!r}")
            continue
        h1, m1, h2, m2 = match.groups()
        start = dtime(int(h1) % 24, int(m1 or 0))
        end = dtime(int(h2) % 24, int(m2 or 0))
        windows.append((start, end))
    return windows


def is_vt(moment: datetime, windows: list[tuple[dtime, dtime]]) -> bool:
    t = moment.time()
    for start, end in windows:
        if start <= end:
            if start <= t < end:
                return True
        elif t >= start or t < end:  # crosses midnight
            return True
    return False


def price_list_attribute(state: State | None) -> list[dict[str, Any]] | None:
    """Return a list attribute like [{start, price, tariff…}, …] if the sensor has one."""
    if state is None:
        return None
    for value in state.attributes.values():
        if (
            isinstance(value, list)
            and value
            and isinstance(value[0], dict)
            and "start" in value[0]
            and "price" in value[0]
        ):
            return value
    return None


def _slots_from_list(
    items: list[dict[str, Any]], factor: float, vt_windows: list[tuple[dtime, dtime]]
) -> list[PriceSlot]:
    """Final prices (already incl. VAT and distribution) – no distribution is added."""
    points: list[tuple[datetime, float, bool, datetime | None]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start = item.get("start")
        start = dt_util.parse_datetime(start) if isinstance(start, str) else start
        if not isinstance(start, datetime):
            continue
        try:
            price = float(item["price"]) * factor
        except (KeyError, TypeError, ValueError):
            continue
        end = item.get("end")
        end = dt_util.parse_datetime(end) if isinstance(end, str) else end
        tariff = str(item.get("tariff") or "").upper()
        low = tariff != "VT" if tariff in ("VT", "NT") else not is_vt(dt_util.as_local(start), vt_windows)
        points.append(
            (dt_util.as_local(start), price, low, dt_util.as_local(end) if isinstance(end, datetime) else None)
        )
    points.sort(key=lambda p: p[0])
    default = _default_step([p[0] for p in points])
    slots = []
    for i, (start, price, low, end) in enumerate(points):
        if end is None:
            end = points[i + 1][0] if i + 1 < len(points) else start + default
            end = min(end, start + default)
        slots.append(PriceSlot(start=start, end=end, spot=price, distribution=0.0, low_tariff=low))
    return slots


def _default_step(starts: list[datetime]) -> timedelta:
    gaps = [b - a for a, b in zip(starts, starts[1:]) if b > a]
    return min(gaps) if gaps else timedelta(hours=1)


def parse_prices(
    state: State | None,
    *,
    dist_vt: float = 0.0,
    dist_nt: float = 0.0,
    vt_windows: list[tuple[dtime, dtime]] | None = None,
) -> list[PriceSlot]:
    """Read price slots from a sensor.

    Two formats are supported:
    - a list attribute [{start, price, tariff?, end?}, …] with the *final* price
      (incl. VAT and distribution) – distribution settings are ignored;
    - Czech Energy Spot Prices: attributes "ISO time" → spot price, to which the
      configured VT/NT distribution is added.
    """
    if state is None:
        return []
    unit = str(state.attributes.get("unit_of_measurement") or "")
    factor = 0.001 if "MWh" in unit else 1.0
    items = price_list_attribute(state)
    if items is not None:
        return _slots_from_list(items, factor, vt_windows or [])
    points: list[tuple[datetime, float]] = []
    for key, value in state.attributes.items():
        if not isinstance(key, str) or not key[:1].isdigit():
            continue
        moment = dt_util.parse_datetime(key)
        if moment is None:
            continue
        try:
            points.append((dt_util.as_local(moment), float(value) * factor))
        except (TypeError, ValueError):
            continue
    if not points:
        return []
    points.sort()
    gaps = [b[0] - a[0] for a, b in zip(points, points[1:]) if b[0] > a[0]]
    default = min(gaps) if gaps else timedelta(hours=1)
    windows = vt_windows or []
    slots = []
    for i, (start, spot) in enumerate(points):
        end = points[i + 1][0] if i + 1 < len(points) else start + default
        end = min(end, start + default)  # a gap in the data is not one huge slot
        low = not is_vt(start, windows)
        slots.append(
            PriceSlot(
                start=start,
                end=end,
                spot=spot,
                distribution=dist_nt if low else dist_vt,
                low_tariff=low,
            )
        )
    return slots


def extend_with_estimate(
    slots: list[PriceSlot],
    deadline: datetime,
    vt_windows: list[tuple[dtime, dtime]] | None = None,
    dist_vt: float = 0.0,
    dist_nt: float = 0.0,
) -> list[PriceSlot]:
    """Fill the time between the last published price and the deadline with estimates.

    Day-ahead prices for tomorrow are published around 14:00. Without this,
    a plan made in the morning for "ready by 7:00 tomorrow" would only see today
    and charge in today's slots even if the night turns out much cheaper. With an
    estimate (average of the known prices), only slots that are cheaper than an
    average night are used now; the rest waits for the real prices.
    """
    if not slots or slots[-1].end >= deadline:
        return slots
    step = _default_step([s.start for s in slots])
    recent = [s for s in slots if s.start >= slots[-1].end - timedelta(hours=24)]
    avg_spot = sum(s.spot for s in recent) / len(recent)
    has_distribution = any(s.distribution for s in slots)
    out = list(slots)
    start = slots[-1].end
    while start < deadline:
        low = not is_vt(start, vt_windows or [])
        dist = (dist_nt if low else dist_vt) if has_distribution else 0.0
        out.append(
            PriceSlot(start=start, end=start + step, spot=avg_spot, distribution=dist, low_tariff=low, estimated=True)
        )
        start += step
    return out


def next_deadline(now: datetime, ready_by: dtime) -> datetime:
    candidate = now.replace(
        hour=ready_by.hour, minute=ready_by.minute, second=0, microsecond=0
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def usable_seconds(slot: PriceSlot, now: datetime, deadline: datetime) -> float:
    start = max(slot.start, now)
    end = min(slot.end, deadline)
    return max(0.0, (end - start).total_seconds())


def build_plan(
    slots: list[PriceSlot],
    now: datetime,
    deadline: datetime,
    needed_seconds: float,
    power_kw: float,
    max_price: float | None = None,
) -> Plan:
    """Pick the cheapest slots (may be scattered) to cover needed_seconds before deadline."""
    plan = Plan(slots=[s for s in slots if s.end > now], deadline=deadline)
    plan.needed_seconds = max(0.0, needed_seconds)
    if plan.needed_seconds <= 0:
        return plan
    candidates = [
        s
        for s in plan.slots
        if usable_seconds(s, now, deadline) > 0
        and (max_price is None or s.price <= max_price)
    ]
    candidates.sort(key=lambda s: (s.price, s.start))
    remaining = plan.needed_seconds
    for slot in candidates:
        if remaining <= 0:
            break
        usable = usable_seconds(slot, now, deadline)
        used = min(usable, remaining)
        plan.selected.add(slot.start)
        plan.planned_seconds += used
        plan.estimated_cost += slot.price * power_kw * used / 3600
        remaining -= used
    return plan


def slot_at(slots: list[PriceSlot], moment: datetime) -> PriceSlot | None:
    for slot in slots:
        if slot.start <= moment < slot.end:
            return slot
    return None


# --------------------------------------------------------- Home Assistant


DEFAULT_CONFIG: dict[str, Any] = {
    "mode": MODE_MANUAL,
    "target_type": TARGET_HOURS,
    "target_hours": 3.0,
    "target_energy": 20.0,
    "ready_by": "07:00",
    # Fixed date for the deadline (YYYY-MM-DD) chosen as "tomorrow"/"day after";
    # None = nearest occurrence of ready_by. Cleared once that deadline passes.
    "ready_date": None,
    "max_price": 0.0,  # 0 = no limit (in cheapest mode)
}


class EcoVolterScheduler:
    """Keeps scheduler settings and progress, decides whether to charge now."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: EcoVolterCoordinator,
        entry_id: str,
        options: dict[str, Any],
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"ecovolter.scheduler.{entry_id}"
        )
        self.price_entity: str | None = options.get("price_entity") or None
        self.dist_vt = float(options.get("distribution_vt", 0.0) or 0.0)
        self.dist_nt = float(options.get("distribution_nt", 0.0) or 0.0)
        try:
            self.vt_windows = parse_vt_windows(options.get("vt_windows", ""))
        except ValueError:
            _LOGGER.warning("EcoVolter: invalid VT windows %r", options.get("vt_windows"))
            self.vt_windows = []

        self.config: dict[str, Any] = dict(DEFAULT_CONFIG)
        # Target reached: stay done (also after unplug/replug and past the
        # deadline) until the user sets a new target/deadline/mode or re-arms.
        self.finished = False
        # progress of the current cycle (until the next deadline)
        self.cycle_deadline: str | None = None
        self.delivered_seconds = 0.0
        self.delivered_kwh = 0.0

        self.plan = Plan()
        self.slots: list[PriceSlot] = []
        self.charge_now = False
        self.reason = ""
        self._last_tick: float | None = None
        self._last_command: float = 0.0
        self._commanded: bool | None = None
        self._override_desired: bool | None = None
        self._was_connected: bool | None = None
        self._plugged_at: float = -1e9
        self._detect_at = -1e9
        self._detected: str | None = None

    # ---- persistence

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.config.update(
            {k: v for k, v in (data.get("config") or {}).items() if k in DEFAULT_CONFIG}
        )
        progress = data.get("progress") or {}
        self.finished = bool(progress.get("finished", False))
        self.cycle_deadline = progress.get("deadline")
        self.delivered_seconds = float(progress.get("seconds", 0.0))
        self.delivered_kwh = float(progress.get("kwh", 0.0))

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "config": self.config,
            "progress": {
                "deadline": self.cycle_deadline,
                "seconds": round(self.delivered_seconds, 1),
                "kwh": round(self.delivered_kwh, 4),
                "finished": self.finished,
            },
        }

    def _save(self, delay: float = 30) -> None:
        self._store.async_delay_save(self._data_to_save, delay)

    async def async_flush(self) -> None:
        await self._store.async_save(self._data_to_save())

    @callback
    def async_flush_on_unload(self) -> None:
        self.hass.async_create_task(self.async_flush())

    # ---- settings (called by select/number/time entities)

    @callback
    def set_option(self, key: str, value: Any) -> None:
        rearm = key in ("mode", "target_type", "target_hours", "target_energy", "ready_by", "ready_date")
        if self.config.get(key) == value:
            # Setting the same target again (e.g. a daily automation) starts a
            # new plan after the previous one was completed.
            if rearm and self.finished:
                self.rearm()
            return
        self.config[key] = value
        if rearm and self.finished:
            # new plan after a completed one: start counting from zero
            self.finished = False
            self.delivered_seconds = 0.0
            self.delivered_kwh = 0.0
        if key in ("mode", "target_type", "target_hours", "target_energy"):
            self._override_desired = None
        if key == "mode" and value == MODE_MANUAL:
            self.charge_now = False
        if key in ("target_type", "target_hours", "target_energy", "ready_by", "ready_date"):
            # a new target starts a new cycle
            self.cycle_deadline = None
        self._save(1)
        self.recalculate(dt_util.now())
        self.coordinator.async_update_listeners()
        self.hass.async_create_task(self.async_apply())

    @callback
    def rearm(self) -> None:
        """Start a new plan for the current target ("charge again")."""
        self.finished = False
        self.delivered_seconds = 0.0
        self.delivered_kwh = 0.0
        self.cycle_deadline = None
        self._override_desired = None
        self._save(1)
        self.recalculate(dt_util.now())
        self.coordinator.async_update_listeners()
        self.hass.async_create_task(self.async_apply())

    @property
    def mode(self) -> str:
        return self.config["mode"]

    def deadline(self, now: datetime) -> datetime:
        date_str = self.config.get("ready_date")
        if date_str:
            try:
                day = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                day = None
            if day is not None:
                fixed = datetime.combine(
                    day, self.ready_by, tzinfo=dt_util.get_default_time_zone()
                )
                if fixed > now:
                    return fixed
            # the chosen day is over – back to the daily deadline
            self.config["ready_date"] = None
            self._save(1)
        return next_deadline(now, self.ready_by)

    def ready_day(self, now: datetime | None = None) -> str:
        now = now or dt_util.now()
        offset = (self.deadline(now).date() - now.date()).days
        return {0: READY_TODAY, 1: READY_TOMORROW}.get(offset, READY_DAY_AFTER)

    @callback
    def set_ready_day(self, day: str) -> None:
        now = dt_util.now()
        if day == READY_TODAY:
            value = None
        else:
            offset = 1 if day == READY_TOMORROW else 2
            value = (now.date() + timedelta(days=offset)).isoformat()
        self.set_option("ready_date", value)

    @property
    def ready_by(self) -> dtime:
        try:
            hour, minute = str(self.config["ready_by"]).split(":")[:2]
            return dtime(int(hour), int(minute))
        except (ValueError, TypeError):
            return dtime(7, 0)

    # ---- inputs from the charger

    def _power_kw(self) -> float:
        data = self.coordinator.data or {}
        status, settings = data.get("status", {}), data.get("settings", {})
        try:
            actual = float(status.get("actualPower") or status.get("power") or 0)
        except (TypeError, ValueError):
            actual = 0.0
        if actual > 0.5:
            return actual
        current = float(settings.get("targetCurrent") or 16)
        phases = 3 if settings.get("isThreePhaseModeEnable") else 1
        return current * PHASE_VOLTAGE * phases / 1000

    def _is_charging(self) -> bool:
        status = (self.coordinator.data or {}).get("status", {})
        return bool(status.get("isCharging", status.get("charging", False)))

    def _is_connected(self) -> bool:
        status = (self.coordinator.data or {}).get("status", {})
        return bool(status.get("isVehicleConnected", status.get("vehicleConnected", False)))

    def _charging_enabled(self) -> bool | None:
        value = (self.coordinator.data or {}).get("settings", {}).get("isChargingEnable")
        return None if value is None else bool(value)

    def resolve_price_entity(self) -> str | None:
        if self.price_entity:
            return self.price_entity
        # A sensor with a list of final prices ([{start, price, …}]) wins.
        now = monotonic.monotonic()
        if now - self._detect_at > 300:
            self._detect_at = now
            self._detected = next(
                (
                    st.entity_id
                    for st in self.hass.states.async_all("sensor")
                    if price_list_attribute(st) is not None
                ),
                None,
            )
        if self._detected and self.hass.states.get(self._detected) is not None:
            return self._detected
        for entity_id in AUTO_PRICE_ENTITIES:
            if self.hass.states.get(entity_id) is not None:
                return entity_id
        return None

    # ---- planning

    def needed_seconds(self) -> float:
        if self.finished:
            return 0.0
        if self.config["target_type"] == TARGET_ENERGY:
            remaining_kwh = float(self.config["target_energy"]) - self.delivered_kwh
            power = self._power_kw()
            return max(0.0, remaining_kwh / power * 3600) if power > 0 else 0.0
        return max(0.0, float(self.config["target_hours"]) * 3600 - self.delivered_seconds)

    def recalculate(self, now: datetime) -> None:
        deadline = self.deadline(now)
        if self.cycle_deadline != deadline.isoformat():
            # new cycle: forget what was charged for the previous deadline
            if self.cycle_deadline is not None and not self.finished:
                self.delivered_seconds = 0.0
                self.delivered_kwh = 0.0
            self.cycle_deadline = deadline.isoformat()
            self._save(1)

        entity_id = self.resolve_price_entity()
        state = self.hass.states.get(entity_id) if entity_id else None
        self.slots = parse_prices(
            state, dist_vt=self.dist_vt, dist_nt=self.dist_nt, vt_windows=self.vt_windows
        )
        prices_until = self.slots[-1].end if self.slots else None
        horizon = extend_with_estimate(
            self.slots, deadline, self.vt_windows, self.dist_vt, self.dist_nt
        ) if self.slots and self.slots[-1].end > now else self.slots
        max_price = float(self.config["max_price"] or 0) or None
        self.plan = build_plan(
            horizon, now, deadline, self.needed_seconds(), self._power_kw(), max_price
        )
        self.plan.prices_until = prices_until
        current = slot_at(self.slots, now)
        mode = self.mode

        if mode == MODE_MANUAL:
            self.charge_now, self.reason = False, "manual"
        elif mode == MODE_LOW_TARIFF:
            self.charge_now = not is_vt(now, self.vt_windows)
            self.reason = "low_tariff" if self.charge_now else "high_tariff"
        elif current is None:
            self.charge_now, self.reason = False, "no_prices"
        elif mode == MODE_PRICE_LIMIT:
            limit = float(self.config["max_price"] or 0)
            self.charge_now = current.price <= limit
            self.reason = "below_limit" if self.charge_now else "above_limit"
        elif mode == MODE_CHEAPEST:
            if self.finished or self.plan.needed_seconds <= 0:
                if not self.finished:
                    self.finished = True
                    self._save(1)
                    _LOGGER.info("EcoVolter scheduler: charging target reached")
                self.charge_now, self.reason = False, "target_reached"
            else:
                self.charge_now = current.start in self.plan.selected
                self.reason = "scheduled" if self.charge_now else "waiting"

    @property
    def current_price(self) -> float | None:
        slot = slot_at(self.slots, dt_util.now())
        return slot.price if slot else None

    def next_start(self) -> datetime | None:
        now = dt_util.now()
        starts = sorted(s for s in self.plan.selected if s > now)
        return starts[0] if starts else None

    # ---- called after each coordinator refresh

    @callback
    def async_tick(self) -> None:
        now_m = monotonic.monotonic()
        if not self.coordinator.last_update_success:
            # charger not answering – do not count stale "charging" data
            self._last_tick = None
            return
        if self._last_tick is not None and self._is_charging():
            dt = min(now_m - self._last_tick, 60)  # ignore gaps (outages, restarts)
            self.delivered_seconds += dt
            self.delivered_kwh += self._power_kw() * dt / 3600
            self._save()
        self._last_tick = now_m
        connected = self._is_connected()
        if connected and self._was_connected is False:
            # New session: forget any manual override from before and let the
            # plan decide right away (the charger may have enabled itself).
            self._plugged_at = now_m
            self._override_desired = None
            self._last_command = -1e9
        self._was_connected = connected
        self.recalculate(dt_util.now())
        self.hass.async_create_task(self.async_apply())

    @callback
    def note_manual_change(self, enabled: bool) -> None:
        """User toggled charging by hand – respect it until the plan changes its mind."""
        if self.mode == MODE_MANUAL:
            return
        self._override_desired = self.charge_now
        self._commanded = enabled

    async def async_apply(self) -> None:
        if self.mode == MODE_MANUAL:
            return
        enabled = self._charging_enabled()
        if enabled is None:
            return
        desired = self.charge_now

        # External change (EcoVolter app, button on the charger…): treat as manual –
        # except right after plug-in, when the charger may enable itself.
        just_plugged = monotonic.monotonic() - self._plugged_at < PLUG_IN_GRACE_SECONDS
        if (
            self._commanded is not None
            and enabled != self._commanded
            and self._override_desired is None
            and not just_plugged
        ):
            self._override_desired = desired
            self._commanded = enabled
        if self._override_desired is not None:
            if desired == self._override_desired:
                return  # plan has not changed since the manual change – keep user's choice
            self._override_desired = None

        if enabled == desired:
            self._commanded = enabled
            return
        if monotonic.monotonic() - self._last_command < MIN_COMMAND_INTERVAL:
            return
        self._last_command = monotonic.monotonic()
        self._commanded = desired
        _LOGGER.info(
            "EcoVolter scheduler: %s charging (%s)", "starting" if desired else "stopping", self.reason
        )
        try:
            await self.coordinator.async_patch_settings(
                {"isChargingEnable": desired}, from_scheduler=True
            )
        except Exception as err:  # noqa: BLE001 – keep the scheduler alive
            _LOGGER.warning("EcoVolter scheduler could not switch charging: %s", err)

    # ---- data for entities / card

    def plan_attributes(self) -> dict[str, Any]:
        now = dt_util.now()
        horizon = [s for s in self.plan.slots if s.start < now + timedelta(hours=36)]
        return {
            "mode": self.mode,
            "reason": self.reason,
            "price_entity": self.resolve_price_entity(),
            "deadline": self.plan.deadline.isoformat() if self.plan.deadline else None,
            "needed_minutes": round(self.plan.needed_seconds / 60),
            "planned_minutes": round(self.plan.planned_seconds / 60),
            "complete": self.plan.complete,
            "finished": self.finished,
            "delivered_minutes": round(self.delivered_seconds / 60),
            "delivered_kwh": round(self.delivered_kwh, 2),
            "estimated_cost": round(self.plan.estimated_cost, 2),
            "prices_until": self.plan.prices_until.isoformat() if self.plan.prices_until else None,
            "waiting_for_prices": self.plan.waiting_for_prices,
            "max_price": float(self.config["max_price"] or 0),
            "slots": [
                [s.start.isoformat(), round(s.price, 3), 1 if s.start in self.plan.selected else 0, 0 if s.low_tariff else 1, 1 if s.estimated else 0]
                for s in horizon
            ],
        }
