"""Data coordinator for EcoVolter."""

from __future__ import annotations

from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EcoVolterApi, EcoVolterAuthError, EcoVolterError
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DIAGNOSTIC_REFRESH_SECONDS,
    DOMAIN,
    MAX_BACKOFF_INTERVAL,
    SETTINGS_REFRESH_SECONDS,
    SETTINGS_VERIFY_AFTER_WRITE_SECONDS,
    STALE_AFTER_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class EcoVolterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate EcoVolter data.

    - Short glitches keep the last good data (no flapping to "unavailable").
    - Longer outages make entities unavailable instead of showing frozen values.
    - While the charger does not answer, polling backs off so it can recover.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api: EcoVolterApi,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api
        self._base_interval = scan_interval
        self._status: dict[str, Any] = {}
        self._settings: dict[str, Any] = {}
        self._diagnostic: dict[str, Any] = {}
        self._last_status_ok: float | None = None
        self._last_diagnostic = 0.0
        self._last_settings = 0.0
        self._failures = 0
        self._logged_unavailable = False

    async def _safe_read(self, name: str, reader) -> dict[str, Any] | None:
        """Read one API section; return None on failure."""
        try:
            return await reader()
        except EcoVolterAuthError:
            raise
        except EcoVolterError as err:
            # Log only the first failure of a series, not every poll.
            if self._failures == 0:
                _LOGGER.debug("EcoVolter %s refresh failed: %s", name, err)
            return None

    def _apply_backoff(self, ok: bool) -> None:
        if ok:
            if self._failures:
                self._failures = 0
                self.update_interval = timedelta(seconds=self._base_interval)
            return
        self._failures += 1
        delay = min(
            MAX_BACKOFF_INTERVAL, self._base_interval * (2 ** min(self._failures, 5))
        )
        self.update_interval = timedelta(seconds=max(self._base_interval, delay))

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._async_update_data_inner()
        except EcoVolterAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err

    async def _async_update_data_inner(self) -> dict[str, Any]:
        now = time.monotonic()

        status = await self._safe_read("status", self.api.async_get_status)
        status_ok = status is not None
        if status_ok:
            self._status = status
            self._last_status_ok = now

        # When the charger is not answering status, do not pile more requests
        # on top of it in the same cycle.
        if status_ok:
            if now - self._last_settings >= SETTINGS_REFRESH_SECONDS or not self._settings:
                settings = await self._safe_read("settings", self.api.async_get_settings)
                if settings is not None:
                    self._settings = settings
                    self._last_settings = now

            if (
                now - self._last_diagnostic >= DIAGNOSTIC_REFRESH_SECONDS
                or not self._diagnostic
            ):
                diagnostic = await self._safe_read(
                    "diagnostic", self.api.async_get_diagnostic
                )
                if diagnostic is not None:
                    self._diagnostic = diagnostic
                    self._last_diagnostic = now

        self._apply_backoff(status_ok)

        if not status_ok:
            stale = (
                self._last_status_ok is None
                or now - self._last_status_ok > STALE_AFTER_SECONDS
            )
            if stale:
                if not self._logged_unavailable:
                    _LOGGER.warning(
                        "EcoVolter %s is not responding; retrying every %ss",
                        self.api.host,
                        int(self.update_interval.total_seconds()),
                    )
                    self._logged_unavailable = True
                raise UpdateFailed("EcoVolter is not responding")
        elif self._logged_unavailable:
            _LOGGER.info("EcoVolter %s is responding again", self.api.host)
            self._logged_unavailable = False

        return self._snapshot()

    def _snapshot(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "settings": self._settings,
            "diagnostic": self._diagnostic,
        }

    async def async_patch_settings(self, settings: dict[str, Any]) -> None:
        """Write settings, update HA immediately, verify shortly afterwards."""
        try:
            await self.api.async_patch_settings(settings)
        except EcoVolterError as err:
            raise HomeAssistantError(f"EcoVolter: zápis se nezdařil ({err})") from err

        # Optimistic local update makes controls react immediately.
        self._settings = {**self._settings, **settings}

        # Some firmware briefly returns the old value right after a PATCH, so
        # do not read back immediately – verify a few seconds later instead.
        self._last_settings = (
            time.monotonic() - SETTINGS_REFRESH_SECONDS + SETTINGS_VERIFY_AFTER_WRITE_SECONDS
        )
        self.async_set_updated_data(self._snapshot())
