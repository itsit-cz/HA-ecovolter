"""Data coordinator for EcoVolter."""

from __future__ import annotations

from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EcoVolterApi, EcoVolterError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class EcoVolterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate EcoVolter data."""

    def __init__(self, hass: HomeAssistant, api: EcoVolterApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self._diagnostic: dict[str, Any] = {}
        self._last_diagnostic = 0.0

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            status = await self.api.async_get_status()
            settings = await self.api.async_get_settings()

            if time.monotonic() - self._last_diagnostic >= 60 or not self._diagnostic:
                self._diagnostic = await self.api.async_get_diagnostic()
                self._last_diagnostic = time.monotonic()

            return {
                "status": status,
                "settings": settings,
                "diagnostic": self._diagnostic,
            }
        except EcoVolterError as err:
            raise UpdateFailed(str(err)) from err

    async def async_patch_settings(self, settings: dict[str, Any]) -> None:
        await self.api.async_patch_settings(settings)
        await self.async_request_refresh()
