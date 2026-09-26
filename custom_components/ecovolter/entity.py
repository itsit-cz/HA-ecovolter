"""Base EcoVolter entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EcoVolterCoordinator


class EcoVolterEntity(CoordinatorEntity[EcoVolterCoordinator]):
    """Base EcoVolter entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EcoVolterCoordinator,
        entry_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._device_name = device_name

    @property
    def device_info(self) -> DeviceInfo:
        diagnostic = self.coordinator.data.get("diagnostic", {})
        serial = (
            diagnostic.get("serialNumber")
            or diagnostic.get("serial")
            or diagnostic.get("deviceSerialNumber")
        )
        model = (
            diagnostic.get("model")
            or diagnostic.get("type")
            or "EcoVolter"
        )
        return DeviceInfo(
            identifiers={(DOMAIN, str(serial or self._entry_id))},
            name=self._device_name,
            manufacturer="REV Charger",
            model=str(model),
            serial_number=str(serial) if serial is not None else None,
            configuration_url=f"http://{self.coordinator.api.host}",
        )
