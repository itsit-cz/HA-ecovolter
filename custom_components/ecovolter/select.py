"""Select entities for the EcoVolter charging scheduler."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EcoVolterConfigEntry
from .entity import EcoVolterEntity
from .scheduler import MODES, TARGET_TYPES


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
        ]
    )


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
