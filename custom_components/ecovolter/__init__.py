"""EcoVolter integration."""

from __future__ import annotations

import hashlib
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import EcoVolterApi
from .const import CONF_SCAN_INTERVAL, CONF_SECRET, DEFAULT_SCAN_INTERVAL, PLATFORMS
from .coordinator import EcoVolterCoordinator
from .scheduler import EcoVolterScheduler

type EcoVolterConfigEntry = ConfigEntry[EcoVolterCoordinator]

CARD_ROUTE = "/ecovolter/ecovolter-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "ecovolter-card.js"


def _file_hash(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:10]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up EcoVolter frontend resources."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_ROUTE, str(CARD_PATH), False)]
    )
    # Cache-bust by file content, so browsers and especially the mobile
    # Companion app always load the current card after an update.
    card_hash = await hass.async_add_executor_job(_file_hash, CARD_PATH)
    add_extra_js_url(hass, f"{CARD_ROUTE}?h={card_hash}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EcoVolterConfigEntry) -> bool:
    """Set up EcoVolter from a config entry."""
    api = EcoVolterApi(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_SECRET],
    )
    scan_interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    coordinator = EcoVolterCoordinator(hass, api, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    scheduler = EcoVolterScheduler(hass, coordinator, entry.entry_id, dict(entry.options))
    await scheduler.async_load()
    coordinator.scheduler = scheduler
    scheduler.recalculate(dt_util.now())
    entry.async_on_unload(coordinator.async_add_listener(scheduler.async_tick))
    entry.async_on_unload(scheduler.async_flush_on_unload)

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: EcoVolterConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: EcoVolterConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
