"""Shared HTTP client for the TfNSW Open Data Hub.

Transport APIs (Trip Planner, Live Traffic, Maritime, ...) use keys from the TfNSW Open Data Hub
(opendata.transport.nsw.gov.au), not API.NSW. Auth is a single `Authorization: apikey <key>` header,
and one API token (profile -> API Tokens) works for every API, so one key covers the transport and roads servers.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from .client import ApiNswError

BASE_URL = "https://api.transport.nsw.gov.au"

# There is a per-second rate limit (bursts get 429). It is not a daily quota and clears quickly.
MIN_INTERVAL_SECONDS = 0.3
RETRY_DELAYS_SECONDS = (1.0, 2.0)


API_KEY_ENV = "NSW_TRANSPORT_API_KEY"


def client_from_env() -> TfnswClient:
    key = os.environ.get(API_KEY_ENV, "")
    if not key:
        raise ApiNswError(
            f"{API_KEY_ENV} environment variable is not set. Register at "
            "https://opendata.transport.nsw.gov.au/data/user/register, then create a key under "
            "your profile -> API Tokens."
        )
    return TfnswClient(key)


class TfnswClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ApiNswError("A TfNSW Open Data API key is required.")
        self._http = http or httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={"Authorization": f"apikey {api_key}"},
        )
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _throttled(self, method: str, path: str, params: dict[str, Any] | None, json: Any) -> httpx.Response:
        # Space requests out: one tool call can make several requests (two place lookups + trip) and hit the limit.
        async with self._lock:
            wait = self._last_request + MIN_INTERVAL_SECONDS - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()
        return await self._http.request(method, path, params=params, json=json)

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json: Any) -> Any:
        return await self.request("POST", path, json=json)

    async def request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None) -> Any:
        try:
            for delay in RETRY_DELAYS_SECONDS:
                resp = await self._throttled(method, path, params, json)
                if resp.status_code != 429:
                    break
                await asyncio.sleep(delay)
            else:
                resp = await self._throttled(method, path, params, json)
        except httpx.HTTPError as e:
            raise ApiNswError(f"Could not connect to TfNSW Open Data: {e}") from e

        if resp.status_code in (401, 403):
            raise ApiNswError(
                f"TfNSW Open Data rejected the API key (HTTP {resp.status_code}). "
                "Check NSW_TRANSPORT_API_KEY, or create a new key under your profile -> API Tokens at "
                "https://opendata.transport.nsw.gov.au/data/user/login."
            )
        if resp.status_code == 429:
            raise ApiNswError("TfNSW Open Data rate limit exceeded. Try again later.")
        if resp.status_code >= 400:
            raise ApiNswError(f"TfNSW Open Data error (HTTP {resp.status_code}): {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError as e:
            raise ApiNswError("TfNSW Open Data returned a non-JSON response.") from e
