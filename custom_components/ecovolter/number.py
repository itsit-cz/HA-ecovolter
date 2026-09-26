"""Number controls for EcoVolter."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfElectricCurrent
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
    async_add_entities(
        [EcoVolterCurrentNumber(entry.runtime_data, entry.entry_id, entry.title)]
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
