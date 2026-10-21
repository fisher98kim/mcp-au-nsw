"""API.NSW 공통 HTTP 클라이언트.

API.NSW(api.onegov.nsw.gov.au)의 모든 API는 같은 방식으로 인증한다:
1. API Key/Secret 으로 OAuth client_credentials 토큰을 발급받는다 (약 12시간 유효).
2. 매 요청마다 Bearer 토큰 + apikey + transactionid + requesttimestamp 헤더를 보낸다.

앱 하나에 API 상품 하나만 붙일 수 있으므로, API마다 별도의 클라이언트(키 쌍)를 만든다.
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

# 토큰 만료 직전에 요청이 실패하지 않도록 이만큼 일찍 갱신한다.
TOKEN_REFRESH_MARGIN_SECONDS = 300


class ApiNswError(Exception):
    """API.NSW 호출 실패. 메시지는 LLM/사용자에게 그대로 보여줄 수 있는 형태로 만든다."""


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

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """API를 호출하고 JSON 응답을 돌려준다. 401이면 토큰을 한 번 갱신해서 재시도한다."""
        for attempt in range(2):
            token = await self._get_token(force_refresh=attempt > 0)
            try:
                resp = await self._http.request(
                    method, path, params=params, json=json, headers=self._headers(token)
                )
            except httpx.HTTPError as e:
                raise ApiNswError(f"Could not connect to API.NSW: {e}") from e
            if resp.status_code == 401 and attempt == 0:
                continue
            break

        data = _safe_json(resp)
        if resp.status_code >= 400:
            raise ApiNswError(_describe_error(resp.status_code, data))
        # 일부 API는 HTTP 200 으로도 errorDetails 를 돌려준다.
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
    if status == 429:
        return "API.NSW rate limit exceeded (the free plan allows 2500 calls/month)."
    return f"API.NSW error (HTTP {status}): {str(data)[:300]}"
