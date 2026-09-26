"""Async client for the EcoVolter Local API."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import socket
import time
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import DEFAULT_PORT, DNS_REFRESH_SECONDS, REQUEST_TIMEOUT_SECONDS


class EcoVolterError(Exception):
    """Base EcoVolter exception."""


class EcoVolterAuthError(EcoVolterError):
    """Authentication failed."""


class EcoVolterConnectionError(EcoVolterError):
    """Connection failed."""


class EcoVolterApi:
    """EcoVolter Local API client with cached DNS resolution."""

    def __init__(
        self,
        session: ClientSession,
        host: str,
        secret: str,
        port: int = DEFAULT_PORT,
    ) -> None:
        self._session = session
        self.host = host.strip()
        self._secret = secret.strip()
        self.port = port
        self.resolved_ip: str | None = None
        self.last_resolved: float | None = None

    @property
    def is_ip_address(self) -> bool:
        try:
            ipaddress.ip_address(self.host)
            return True
        except ValueError:
            return False

    async def async_resolve(self, force: bool = False) -> str:
        """Resolve host, preferring IPv4, and cache the result."""
        now = time.monotonic()
        if (
            not force
            and self.resolved_ip
            and self.last_resolved is not None
            and now - self.last_resolved < DNS_REFRESH_SECONDS
        ):
            return self.resolved_ip

        if self.is_ip_address:
            self.resolved_ip = self.host
        else:
            loop = asyncio.get_running_loop()
            try:
                infos = await loop.getaddrinfo(
                    self.host,
                    self.port,
                    family=socket.AF_UNSPEC,
                    type=socket.SOCK_STREAM,
                )
            except OSError as err:
                raise EcoVolterConnectionError(
                    f"Unable to resolve {self.host}"
                ) from err

            addresses = [info[4][0] for info in infos]
            ipv4 = [address for address in addresses if ":" not in address]
            if not addresses:
                raise EcoVolterConnectionError(f"No address found for {self.host}")
            self.resolved_ip = ipv4[0] if ipv4 else addresses[0]

        self.last_resolved = now
        return self.resolved_ip

    def _signature(self, signed_url: str, timestamp: str, body: str) -> str:
        message = f"{signed_url}\n{timestamp}\n{body}".encode()
        return hmac.new(
            self._secret.encode(),
            message,
            hashlib.sha256,
        ).hexdigest()

    async def _request(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> dict[str, Any]:
        ip = await self.async_resolve()
        path = f"/api/v1{endpoint}"

        # The charger API is addressed through the direct resolved IP for speed.
        # HMAC signs the exact URL sent to the charger.
        signed_url = f"https://{ip}:{self.port}{path}"
        body = (
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            if payload is not None
            else ""
        )
        timestamp = str(int(time.time()))
        headers = {
            "Authorization": f"HmacSHA256 {self._signature(signed_url, timestamp, body)}",
            "X-Timestamp": timestamp,
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"

        try:
            async with self._session.request(
                method,
                signed_url,
                data=body if payload is not None else None,
                headers=headers,
                timeout=ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
                ssl=False,
            ) as response:
                if response.status in (401, 403):
                    raise EcoVolterAuthError("Authentication failed")
                if response.status >= 400:
                    response_text = await response.text()
                    raise EcoVolterError(
                        f"HTTP {response.status}: {response_text}"
                    )
                if response.status == 204:
                    return {}
                return await response.json(content_type=None)
        except EcoVolterAuthError:
            raise
        except (ClientError, asyncio.TimeoutError, OSError) as err:
            if retry and not self.is_ip_address:
                await self.async_resolve(force=True)
                return await self._request(method, endpoint, payload, retry=False)
            raise EcoVolterConnectionError(
                "Unable to connect to EcoVolter"
            ) from err

    async def async_get_status(self) -> dict[str, Any]:
        return await self._request("GET", "/charger/status")

    async def async_get_settings(self) -> dict[str, Any]:
        return await self._request("GET", "/charger/settings")

    async def async_get_diagnostic(self) -> dict[str, Any]:
        return await self._request("GET", "/charger/diagnostic")

    async def async_patch_settings(self, settings: dict[str, Any]) -> None:
        await self._request("PATCH", "/charger/settings", settings)
