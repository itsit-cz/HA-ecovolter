"""Switches for EcoVolter."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EcoVolterConfigEntry
from .entity import EcoVolterEntity


@dataclass(frozen=True, kw_only=True)
class EcoVolterSwitchDescription(SwitchEntityDescription):
    api_key: str


SWITCHES = (
    EcoVolterSwitchDescription(
        key="charging_enabled",
        translation_key="charging_enabled",
        api_key="isChargingEnable",
    ),
    EcoVolterSwitchDescription(
        key="three_phase",
        translation_key="three_phase",
        api_key="isThreePhaseModeEnable",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcoVolterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        EcoVolterSwitch(coordinator, entry.entry_id, entry.title, description)
        for description in SWITCHES
    )


class EcoVolterSwitch(EcoVolterEntity, SwitchEntity):
    entity_description: EcoVolterSwitchDescription

    def __init__(self, coordinator, entry_id, device_name, description):
        super().__init__(coordinator, entry_id, device_name)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"

    @property
    def is_on(self):
        value = self.coordinator.data.get("settings", {}).get(
            self.entity_description.api_key
        )
        return bool(value) if value is not None else None

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_patch_settings(
            {self.entity_description.api_key: True}
        )

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_patch_settings(
            {self.entity_description.api_key: False}
        )
