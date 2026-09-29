"""Data coordinator for EcoVolter."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EcoVolterApi, EcoVolterError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)
_DIAGNOSTIC_INTERVAL = 60


class EcoVolterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate EcoVolter data without dropping good data on partial failures."""

    def __init__(self, hass: HomeAssistant, api: EcoVolterApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self._status: dict[str, Any] = {}
        self._settings: dict[str, Any] = {}
        self._diagnostic: dict[str, Any] = {}
        self._last_diagnostic = 0.0
        self._last_settings = 0.0
        self._write_lock = asyncio.Lock()

    async def _safe_read(
        self,
        name: str,
        reader,
        previous: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Read one API section, preserving the last good value on failure."""
        try:
            return await reader(), True
        except EcoVolterError as err:
            _LOGGER.warning("EcoVolter %s refresh failed; keeping last good data: %s", name, err)
            return previous, False

    async def _async_update_data(self) -> dict[str, Any]:
        """Refresh independent API sections and keep last known good values."""
        status, status_ok = await self._safe_read(
            "status", self.api.async_get_status, self._status
        )
        now = time.monotonic()
        settings_ok = True
        if now - self._last_settings >= 60 or not self._settings:
            settings, settings_ok = await self._safe_read(
                "settings", self.api.async_get_settings, self._settings
            )
            if settings_ok:
                self._settings = settings
                self._last_settings = now

        self._status = status

        if now - self._last_diagnostic >= _DIAGNOSTIC_INTERVAL or not self._diagnostic:
            diagnostic, diagnostic_ok = await self._safe_read(
                "diagnostic", self.api.async_get_diagnostic, self._diagnostic
            )
            if diagnostic_ok:
                self._diagnostic = diagnostic
                self._last_diagnostic = now

        # Initial setup still needs at least one useful response. After that,
        # temporary failures retain the previous data instead of making every
        # EcoVolter entity unavailable.
        if not status_ok and not settings_ok and not (self._status or self._settings):
            raise UpdateFailed("Unable to read EcoVolter status or settings")

        return {
            "status": self._status,
            "settings": self._settings,
            "diagnostic": self._diagnostic,
        }

    async def async_patch_settings(self, settings: dict[str, Any]) -> None:
        """Write settings, update HA immediately, then confirm them from the charger."""
        async with self._write_lock:
            await self.api.async_patch_settings(settings)

            # Optimistic local update makes controls react immediately.
            self._settings = {**self._settings, **settings}
            current = self.data or {}
            self.async_set_updated_data(
                {
                    "status": current.get("status", self._status),
                    "settings": self._settings,
                    "diagnostic": current.get("diagnostic", self._diagnostic),
                }
            )

            # Do not immediately GET settings after a PATCH. Some EcoVolter
            # firmware briefly returns the old value, which makes HA controls jump
            # backwards. Keep the acknowledged local value and verify settings on
            # the normal one-minute settings refresh.
            self._last_settings = time.monotonic()
