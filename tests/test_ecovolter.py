"""Tests for the EcoVolter integration.

Run: pip install pytest-homeassistant-custom-component && pytest tests
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import time
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
import pytest

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ecovolter.api import (
    EcoVolterApi,
    EcoVolterAuthError,
    EcoVolterConnectionError,
    EcoVolterError,
)
from custom_components.ecovolter.const import CONF_SCAN_INTERVAL, CONF_SECRET, DOMAIN
from custom_components.ecovolter.coordinator import EcoVolterCoordinator

STATUS = {
    "isVehicleConnected": True,
    "isCharging": True,
    "actualPower": 7.1,
    "chargedEnergy": 3.2,
    "currentL1": 10.1,
    "currentL2": 10.0,
    "currentL3": 0.2,
    "voltageL1": 231,
    "voltageL2": 230,
    "voltageL3": 229,
}
SETTINGS = {"isChargingEnable": True, "isThreePhaseModeEnable": False, "targetCurrent": 10}
DIAG = {"serialNumber": "ABC123", "totalChargedEnergy": 100.0}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


# ---------------------------------------------------------------- API client


@pytest.fixture
def local_sockets(socket_enabled):
    """Allow the fake charger HTTP server on localhost."""
    yield


async def _server(aiohttp_server, handler):
    app = web.Application()
    app.router.add_route("*", "/api/v1/charger/{name}", handler)
    return await aiohttp_server(app)


async def test_api_headers_and_json(hass: HomeAssistant, aiohttp_server, local_sockets) -> None:
    seen = {}

    async def handler(request):
        seen.update(request.headers)
        return web.json_response(STATUS)

    server = await _server(aiohttp_server, handler)
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    api = EcoVolterApi(async_get_clientsession(hass), "127.0.0.1", "secret", port=server.port)
    api.resolved_ip = f"127.0.0.1:{server.port}"
    api.last_resolved = time.monotonic()
    assert (await api.async_get_status())["isCharging"] is True
    assert seen["Connection"].lower() == "close"
    assert seen["Authorization"].startswith("HmacSHA256 ")
    assert "X-Timestamp" in seen


@pytest.mark.parametrize(
    ("response", "exc"),
    [
        (lambda: web.Response(text='{"isCharg'), EcoVolterError),
        (lambda: web.Response(text="[1,2]"), EcoVolterError),
        (lambda: web.Response(status=401), EcoVolterAuthError),
        (lambda: web.Response(status=500, text="oops"), EcoVolterError),
    ],
)
async def test_api_bad_responses(hass, aiohttp_server, local_sockets, response, exc) -> None:
    async def handler(request):
        return response()

    server = await _server(aiohttp_server, handler)
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    api = EcoVolterApi(async_get_clientsession(hass), "127.0.0.1", "s")
    api.resolved_ip = f"127.0.0.1:{server.port}"
    api.last_resolved = time.monotonic()
    with pytest.raises(exc):
        await api.async_get_status()


async def test_api_timeout_not_retried_on_same_ip(hass, aiohttp_server, local_sockets) -> None:
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        await asyncio.sleep(10)
        return web.json_response({})

    server = await _server(aiohttp_server, handler)
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    api = EcoVolterApi(async_get_clientsession(hass), "charger.example", "s")
    api.resolved_ip = f"127.0.0.1:{server.port}"
    api.last_resolved = time.monotonic()

    async def same_ip(force=False):
        return api.resolved_ip

    with (
        patch("custom_components.ecovolter.api.REQUEST_TIMEOUT_SECONDS", 0.3),
        patch.object(api, "async_resolve", side_effect=same_ip),
        pytest.raises(EcoVolterConnectionError),
    ):
        await api.async_get_status()
    assert calls == 1


# --------------------------------------------------------------- Coordinator


def _api(status=STATUS):
    api = AsyncMock(spec=EcoVolterApi)
    api.host = "charger"
    api.async_get_status.return_value = status
    api.async_get_settings.return_value = SETTINGS
    api.async_get_diagnostic.return_value = DIAG
    return api


async def test_coordinator_backoff_stale_and_recovery(hass: HomeAssistant) -> None:
    api = _api()
    coord = EcoVolterCoordinator(hass, api, 2)
    data = await coord._async_update_data()
    assert data["settings"]["targetCurrent"] == 10

    # short outage: keep last data, slow down, do not hit settings/diagnostic
    api.async_get_status.side_effect = EcoVolterConnectionError("down")
    api.async_get_settings.reset_mock()
    data = await coord._async_update_data()
    assert data["status"]["isCharging"] is True
    assert coord.update_interval > timedelta(seconds=2)
    for _ in range(6):
        await coord._async_update_data()
    assert coord.update_interval == timedelta(seconds=30)
    api.async_get_settings.assert_not_called()

    # long outage: become unavailable instead of frozen values
    coord._last_status_ok -= 120
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()

    # recovery
    api.async_get_status.side_effect = None
    await coord._async_update_data()
    assert coord.update_interval == timedelta(seconds=2)


async def test_patch_is_optimistic_and_verified_soon(hass: HomeAssistant) -> None:
    api = _api()
    coord = EcoVolterCoordinator(hass, api, 2)
    coord.async_set_updated_data(await coord._async_update_data())
    await coord.async_patch_settings({"targetCurrent": 14})
    assert coord.data["settings"]["targetCurrent"] == 14
    api.async_patch_settings.side_effect = EcoVolterConnectionError("x")
    from homeassistant.exceptions import HomeAssistantError

    with pytest.raises(HomeAssistantError):
        await coord.async_patch_settings({"targetCurrent": 6})


# ----------------------------------------------------------- Full set-up


async def test_setup_entities_and_options(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: "10.0.0.5", CONF_SECRET: "s"}, unique_id="abc123"
    )
    entry.add_to_hass(hass)
    # The frontend component needs the hass_frontend package; fake the bits we use.
    hass.config.components.update({"frontend", "http"})
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with (
        patch("custom_components.ecovolter.add_extra_js_url") as js_mock,
        patch.object(EcoVolterApi, "async_get_status", return_value=STATUS),
        patch.object(EcoVolterApi, "async_get_settings", return_value=SETTINGS),
        patch.object(EcoVolterApi, "async_get_diagnostic", return_value=DIAG),
        patch.object(EcoVolterApi, "async_patch_settings", return_value=None) as patch_mock,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert "/ecovolter/ecovolter-card.js?h=" in js_mock.call_args[0][1]

        from homeassistant.helpers import entity_registry as er

        reg = er.async_get(hass)
        entries = er.async_entries_for_config_entry(reg, entry.entry_id)
        states = [hass.states.get(e.entity_id) for e in entries]
        # 18 charger entities + 10 scheduler entities
        assert len(states) == 28
        # without a price sensor only the total price is unavailable
        assert [
            e.translation_key
            for e, s in zip(entries, states)
            if s is None or s.state == "unavailable"
        ] == ["current_total_price"]
        number = next(
            hass.states.get(e.entity_id) for e in entries if e.translation_key == "target_current" and e.domain == "number"
        )
        assert float(number.state) == 10

        await hass.services.async_call(
            "number", "set_value", {"entity_id": number.entity_id, "value": 13}, blocking=True
        )
        patch_mock.assert_awaited_with({"targetCurrent": 13})
        assert float(hass.states.get(number.entity_id).state) == 13

        assert entry.runtime_data.update_interval == timedelta(seconds=2)
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SCAN_INTERVAL: 5}
        )
        await hass.async_block_till_done()
        assert entry.options[CONF_SCAN_INTERVAL] == 5
        assert entry.runtime_data.update_interval == timedelta(seconds=5)
