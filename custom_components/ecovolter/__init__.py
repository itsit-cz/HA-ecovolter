"""EcoVolter integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EcoVolterApi
from .const import CONF_SECRET, DOMAIN, PLATFORMS
from .coordinator import EcoVolterCoordinator

type EcoVolterConfigEntry = ConfigEntry[EcoVolterCoordinator]


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
