"""Sensors for EcoVolter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import UnitOfElectricCurrent, UnitOfElectricPotential, UnitOfEnergy, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EcoVolterConfigEntry
from .entity import EcoVolterEntity


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _phase_value(data: dict[str, Any], field: str, phase: int) -> Any:
    aliases = (
        f"{field}L{phase}",
        f"{field}{phase}",
        f"l{phase}{field[0].upper()}{field[1:]}",
        f"L{phase}{field[0].upper()}{field[1:]}",
    )
    value = _pick(data, *aliases)
    if value is not None:
        return value
    plural = data.get(f"{field}s")
    if isinstance(plural, list) and len(plural) >= phase:
        return plural[phase - 1]
    if isinstance(plural, dict):
        return plural.get(f"L{phase}") or plural.get(str(phase))
    return None


@dataclass(frozen=True, kw_only=True)
class EcoVolterSensorDescription(SensorEntityDescription):
    section: str
    value_fn: Callable[[dict[str, Any]], Any]


SENSORS = (
    EcoVolterSensorDescription(
        key="power",
        translation_key="power",
        section="status",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _pick(d, "actualPower", "power"),
    ),
    EcoVolterSensorDescription(
        key="session_energy",
        translation_key="session_energy",
        section="status",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: _pick(d, "chargedEnergy", "sessionChargedEnergy"),
    ),
    EcoVolterSensorDescription(
        key="total_energy",
        translation_key="total_energy",
        section="diagnostic",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: _pick(d, "totalChargedEnergy"),
    ),
    EcoVolterSensorDescription(
        key="charging_count",
        translation_key="charging_count",
        section="diagnostic",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: _pick(d, "totalChargingCount"),
    ),
    EcoVolterSensorDescription(
        key="total_charging_time",
        translation_key="total_charging_time",
        section="diagnostic",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: _pick(d, "totalChargingTime"),
    ),
    *tuple(
        EcoVolterSensorDescription(
            key=f"current_l{phase}",
            translation_key=f"current_l{phase}",
            section="status",
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=lambda d, p=phase: _phase_value(d, "current", p),
        )
        for phase in (1, 2, 3)
    ),
    *tuple(
        EcoVolterSensorDescription(
            key=f"voltage_l{phase}",
            translation_key=f"voltage_l{phase}",
            section="status",
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            device_class=SensorDeviceClass.VOLTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=lambda d, p=phase: _phase_value(d, "voltage", p),
        )
        for phase in (1, 2, 3)
    ),
    EcoVolterSensorDescription(
        key="active_phases",
        translation_key="active_phases",
        section="status",
        value_fn=lambda d: _pick(d, "activePhases", "phaseCount", "numberOfActivePhases"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcoVolterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        EcoVolterSensor(coordinator, entry.entry_id, entry.title, description)
        for description in SENSORS
    )


class EcoVolterSensor(EcoVolterEntity, SensorEntity):
    entity_description: EcoVolterSensorDescription

    def __init__(self, coordinator, entry_id, device_name, description):
        super().__init__(coordinator, entry_id, device_name)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"

    @property
    def native_value(self):
        section = self.coordinator.data.get(self.entity_description.section, {})
        return self.entity_description.value_fn(section)
