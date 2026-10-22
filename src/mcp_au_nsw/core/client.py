"""Shared HTTP client for API.NSW.

Every API on API.NSW (api.onegov.nsw.gov.au) authenticates the same way:
1. Exchange the API key/secret for an OAuth client_credentials token (valid ~12 hours).
2. Send the Bearer token + apikey + transactionid + requesttimestamp headers on every request.

An app can only have one API product, so each API gets its own client (key pair).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

BASE_URL = "https://api.onegov.nsw.gov.au"
TOKEN_PATH = "/oauth/client_credential/accesstoken"

# Refresh this early so requests don't fail right before the token expires.
TOKEN_REFRESH_MARGIN_SECONDS = 300

# Bursts of requests get "Traffic limit exceeded" (HTTP 408) or 429. It is a short-term limit,
# separate from the monthly quota, so space requests out and retry after a pause.
MIN_INTERVAL_SECONDS = 1.0
RETRY_DELAYS_SECONDS = (2.0, 4.0)
RATE_LIMIT_STATUSES = (408, 429)


class ApiNswError(Exception):
    """API.NSW call failed. Messages are written to be shown as-is to the LLM/user."""


class ApiNswClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key or not api_secret:
            raise ApiNswError("API key and secret are required.")
        self._api_key = api_key
        self._api_secret = api_secret
        self._http = http or httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()
        self._throttle_lock = asyncio.Lock()
        self._last_request = 0.0

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get_token(self, *, force_refresh: bool = False) -> str:
        async with self._token_lock:
            if not force_refresh and self._token and time.monotonic() < self._token_expires_at:
                return self._token

            resp = await self._http.get(
                TOKEN_PATH,
                params={"grant_type": "client_credentials"},
                auth=(self._api_key, self._api_secret),
            )
            if resp.status_code != 200:
                raise ApiNswError(
                    f"API.NSW token request failed (HTTP {resp.status_code}). Check your API key/secret."
                )
            data = resp.json()
            self._token = data["access_token"]
            expires_in = int(data.get("expires_in", 3600))
            self._token_expires_at = (
                time.monotonic() + max(expires_in - TOKEN_REFRESH_MARGIN_SECONDS, 60)
            )
            return self._token

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "apikey": self._api_key,
            "Content-Type": "application/json; charset=utf-8",
            "transactionid": str(uuid.uuid4()),
            "requesttimestamp": datetime.now(timezone.utc).strftime("%d/%m/%Y %I:%M:%S %p"),
        }

    async def _send(self, method: str, path: str, params: dict[str, Any] | None, json: Any, token: str) -> httpx.Response:
        async with self._throttle_lock:
            wait = self._last_request + MIN_INTERVAL_SECONDS - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()
        try:
            return await self._http.request(method, path, params=params, json=json, headers=self._headers(token))
        except httpx.HTTPError as e:
            raise ApiNswError(f"Could not connect to API.NSW: {e}") from e

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Call the API and return the JSON response.

        On 401, refresh the token and retry once. On a short-term rate limit, wait and retry.
        """
        refreshed = False
        retries = iter(RETRY_DELAYS_SECONDS)
        while True:
            token = await self._get_token(force_refresh=refreshed)
            resp = await self._send(method, path, params, json, token)
            if resp.status_code == 401 and not refreshed:
                refreshed = True
                continue
            if resp.status_code in RATE_LIMIT_STATUSES and (delay := next(retries, None)) is not None:
                await asyncio.sleep(delay)
                continue
            break

        data = _safe_json(resp)
        if resp.status_code >= 400:
            raise ApiNswError(_describe_error(resp.status_code, data))
        # Some APIs return errorDetails with HTTP 200.
        if isinstance(data, dict) and data.get("errorDetails") and len(data) == 1:
            raise ApiNswError(_describe_error(resp.status_code, data))
        return data


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text


def _describe_error(status: int, data: Any) -> str:
    details = data.get("errorDetails") if isinstance(data, dict) else None
    if isinstance(details, dict):
        details = [details]
    if details:
        msgs = "; ".join(
            f"{d.get('code', '')} {d.get('description') or d.get('message', '')}".strip()
            for d in details
        )
        return f"API.NSW error (HTTP {status}): {msgs}"
    if status in RATE_LIMIT_STATUSES:
        return (
            "API.NSW rate limit exceeded. Wait a moment and try again; "
            "if it keeps happening, the monthly quota (2500 calls on the free plan) may be used up."
        )
    return f"API.NSW error (HTTP {status}): {str(data)[:300]}"
