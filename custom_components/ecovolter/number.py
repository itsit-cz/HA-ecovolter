"""Number controls for EcoVolter."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, UnitOfElectricCurrent, UnitOfEnergy, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EcoVolterConfigEntry
from .const import MAX_CURRENT, MIN_CURRENT
from .entity import EcoVolterEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcoVolterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            EcoVolterCurrentNumber(coordinator, entry.entry_id, entry.title),
            *(
                EcoVolterSchedulerNumber(coordinator, entry.entry_id, entry.title, spec)
                for spec in SCHEDULER_NUMBERS
            ),
        ]
    )


class EcoVolterCurrentNumber(EcoVolterEntity, NumberEntity):
    _attr_translation_key = "target_current"
    _attr_native_min_value = MIN_CURRENT
    _attr_native_max_value = MAX_CURRENT
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, entry_id, device_name):
        super().__init__(coordinator, entry_id, device_name)
        self._attr_unique_id = f"{entry_id}_target_current"

    @property
    def native_value(self):
        return self.coordinator.data.get("settings", {}).get("targetCurrent")

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_patch_settings(
            {"targetCurrent": int(value)}
        )


SCHEDULER_NUMBERS = (
    # key, config key, min, max, step, unit, icon
    ("target_hours", "target_hours", 0, 24, 0.25, UnitOfTime.HOURS, "mdi:timer-outline"),
    ("target_energy", "target_energy", 0, 150, 1, UnitOfEnergy.KILO_WATT_HOUR, "mdi:battery-charging"),
    ("max_price", "max_price", 0, 30, 0.1, "CZK/kWh", "mdi:cash-lock"),
    ("target_soc", "target_soc", 10, 100, 1, PERCENTAGE, "mdi:battery-charging-80"),
)


class EcoVolterSchedulerNumber(EcoVolterEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, entry_id, device_name, spec):
        super().__init__(coordinator, entry_id, device_name)
        key, self._option, lo, hi, step, unit, icon = spec
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_native_min_value = lo
        self._attr_native_max_value = hi
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

    @property
    def native_value(self):
        sched = self.coordinator.scheduler
        if self._option == "target_soc":
            return sched.target_soc  # per selected car
        return float(sched.config[self._option])

    @property
    def available(self) -> bool:
        return True

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.scheduler.set_option(self._option, float(value))
