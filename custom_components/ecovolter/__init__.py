"""EcoVolter integration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EcoVolterApi
from .const import CONF_SECRET, DOMAIN, PLATFORMS
from .coordinator import EcoVolterCoordinator

type EcoVolterConfigEntry = ConfigEntry[EcoVolterCoordinator]

CARD_URL = "/ecovolter/ecovolter-card.js?v=0.2.1-dev1"
CARD_ROUTE = "/ecovolter/ecovolter-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "ecovolter-card.js"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up EcoVolter frontend resources."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_ROUTE, str(CARD_PATH), False)]
    )
    add_extra_js_url(hass, CARD_URL)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EcoVolterConfigEntry) -> bool:
    """Set up EcoVolter from a config entry."""
    api = EcoVolterApi(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_SECRET],
    )
    coordinator = EcoVolterCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EcoVolterConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
