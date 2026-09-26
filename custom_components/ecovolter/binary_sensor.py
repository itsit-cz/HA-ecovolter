"""Binary sensors for EcoVolter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EcoVolterConfigEntry
from .entity import EcoVolterEntity


def _bool(data: dict[str, Any], *keys: str) -> bool | None:
    for key in keys:
        if key in data:
            return bool(data[key])
    return None


@dataclass(frozen=True, kw_only=True)
class EcoVolterBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], bool | None]


BINARY_SENSORS = (
    EcoVolterBinaryDescription(
        key="vehicle_connected",
        translation_key="vehicle_connected",
        value_fn=lambda d: _bool(d, "isVehicleConnected", "vehicleConnected"),
    ),
    EcoVolterBinaryDescription(
        key="charging",
        translation_key="charging",
        value_fn=lambda d: _bool(d, "isCharging", "charging"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcoVolterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        EcoVolterBinarySensor(coordinator, entry.entry_id, entry.title, description)
        for description in BINARY_SENSORS
    )


class EcoVolterBinarySensor(EcoVolterEntity, BinarySensorEntity):
    entity_description: EcoVolterBinaryDescription

    def __init__(self, coordinator, entry_id, device_name, description):
        super().__init__(coordinator, entry_id, device_name)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"

    @property
    def is_on(self):
        return self.entity_description.value_fn(
            self.coordinator.data.get("status", {})
        )
