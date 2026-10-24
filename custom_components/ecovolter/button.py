"""Button for the EcoVolter charging scheduler ("charge again")."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EcoVolterConfigEntry
from .entity import EcoVolterEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcoVolterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([EcoVolterRearmButton(entry.runtime_data, entry.entry_id, entry.title)])


class EcoVolterRearmButton(EcoVolterEntity, ButtonEntity):
    """Start a new plan after the charging target was reached."""

    _attr_translation_key = "charge_again"
    _attr_icon = "mdi:restart"

    def __init__(self, coordinator, entry_id, device_name):
        super().__init__(coordinator, entry_id, device_name)
        self._attr_unique_id = f"{entry_id}_charge_again"

    @property
    def available(self) -> bool:
        return True

    async def async_press(self) -> None:
        self.coordinator.scheduler.rearm()
