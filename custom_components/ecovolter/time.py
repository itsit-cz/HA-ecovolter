"""Time entity for the EcoVolter charging scheduler ("ready by")."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EcoVolterConfigEntry
from .entity import EcoVolterEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcoVolterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([EcoVolterReadyBy(entry.runtime_data, entry.entry_id, entry.title)])


class EcoVolterReadyBy(EcoVolterEntity, TimeEntity):
    _attr_translation_key = "ready_by"
    _attr_icon = "mdi:clock-end"

    def __init__(self, coordinator, entry_id, device_name):
        super().__init__(coordinator, entry_id, device_name)
        self._attr_unique_id = f"{entry_id}_ready_by"

    @property
    def native_value(self) -> time:
        return self.coordinator.scheduler.ready_by

    @property
    def available(self) -> bool:
        return True

    async def async_set_value(self, value: time) -> None:
        self.coordinator.scheduler.set_option("ready_by", value.strftime("%H:%M"))
