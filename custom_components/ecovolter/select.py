"""Select entities for the EcoVolter charging scheduler."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EcoVolterConfigEntry
from .entity import EcoVolterEntity
from .scheduler import CAR_OTHER, MODES, READY_DAYS, TARGET_TYPES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcoVolterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            EcoVolterSchedulerSelect(coordinator, entry.entry_id, entry.title, "charging_mode", "mode", MODES),
            EcoVolterSchedulerSelect(coordinator, entry.entry_id, entry.title, "target_type", "target_type", TARGET_TYPES),
            EcoVolterReadyDaySelect(coordinator, entry.entry_id, entry.title),
        ]
    )
    if coordinator.scheduler.cars:
        async_add_entities([EcoVolterCarSelect(coordinator, entry.entry_id, entry.title)])


class EcoVolterSchedulerSelect(EcoVolterEntity, SelectEntity):
    def __init__(self, coordinator, entry_id, device_name, key, option, options):
        super().__init__(coordinator, entry_id, device_name)
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_options = list(options)
        self._option = option
        if key == "target_type":
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def current_option(self) -> str | None:
        return self.coordinator.scheduler.config[self._option]

    @property
    def available(self) -> bool:
        return True  # settings stay editable while the charger is offline

    async def async_select_option(self, option: str) -> None:
        self.coordinator.scheduler.set_option(self._option, option)


class EcoVolterReadyDaySelect(EcoVolterEntity, SelectEntity):
    """Day of the "ready by" deadline: today (nearest), tomorrow, day after."""

    _attr_translation_key = "ready_day"
    _attr_icon = "mdi:calendar-today"
    _attr_options = list(READY_DAYS)

    def __init__(self, coordinator, entry_id, device_name):
        super().__init__(coordinator, entry_id, device_name)
        self._attr_unique_id = f"{entry_id}_ready_day"

    @property
    def current_option(self) -> str:
        return self.coordinator.scheduler.ready_day()

    @property
    def available(self) -> bool:
        return True

    async def async_select_option(self, option: str) -> None:
        self.coordinator.scheduler.set_ready_day(option)


class EcoVolterCarSelect(EcoVolterEntity, SelectEntity):
    """Which car is charging (for % targets). Options = car names + "other"."""

    _attr_translation_key = "car"
    _attr_icon = "mdi:car-electric"

    def __init__(self, coordinator, entry_id, device_name):
        super().__init__(coordinator, entry_id, device_name)
        self._attr_unique_id = f"{entry_id}_car"
        self._attr_options = [c["name"] for c in coordinator.scheduler.cars] + [CAR_OTHER]

    @property
    def current_option(self) -> str:
        car = self.coordinator.scheduler.car
        return car["name"] if car else CAR_OTHER

    @property
    def available(self) -> bool:
        return True

    @property
    def extra_state_attributes(self):
        sched = self.coordinator.scheduler
        return {"ambiguous": sched.car_ambiguous, "car_id": (sched.car or {}).get("id", CAR_OTHER)}

    async def async_select_option(self, option: str) -> None:
        sched = self.coordinator.scheduler
        car_id = next((c["id"] for c in sched.cars if c["name"] == option), CAR_OTHER)
        sched.select_car(car_id)
