"""NSW/TAS 실시간 유가 MCP 서버 (API.NSW Fuel API v2).

필요한 환경변수: NSW_FUEL_API_KEY, NSW_FUEL_API_SECRET
무료 플랜은 월 2500건이라, 참조 데이터(연료 종류/주유소 목록)는 하루 동안 캐싱해서
주유소 검색과 지명 → 좌표 변환은 API 호출 없이 처리한다.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from mcp_au_nsw.core import ApiNswClient, ApiNswError

State = Literal["NSW", "TAS"]

REF_DATA_PATH = "/FuelCheckRefData/v2/fuel/lovs"
PRICES_PATH = "/FuelPriceCheck/v2/fuel/prices"
REF_DATA_TTL_SECONDS = 24 * 60 * 60

# "307-313 Ocean Beach Road, UMINA BEACH NSW 2257" → ("UMINA BEACH", "2257")
_ADDRESS_RE = re.compile(r",\s*([^,]+?)\s+(?:NSW|TAS)\s+(\d{4})\s*$", re.IGNORECASE)

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

mcp = MCPServer(
    name="nsw-fuel",
    instructions=(
        "Live fuel prices for service stations in NSW and TAS, Australia. Prices are in cents per litre. "
        "Call list_fuel_types first if you don't know the fuel type code. "
        "Use search_stations to find a specific station, and find_fuel_prices to find the cheapest fuel in an area."
    ),
)

_client: ApiNswClient | None = None
_ref_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _get_client() -> ApiNswClient:
    global _client
    if _client is None:
        key = os.environ.get("NSW_FUEL_API_KEY", "")
        secret = os.environ.get("NSW_FUEL_API_SECRET", "")
        if not key or not secret:
            raise ToolError(
                "NSW_FUEL_API_KEY / NSW_FUEL_API_SECRET environment variables are not set. "
                "Create an app with the Fuel API at https://api.nsw.gov.au to get a key."
            )
        _client = ApiNswClient(key, secret)
    return _client


async def _call(method: str, path: str, **kwargs: Any) -> Any:
    try:
        return await _get_client().request(method, path, **kwargs)
    except ApiNswError as e:
        raise ToolError(str(e)) from e


async def _ref_data(state: State) -> dict[str, Any]:
    cached = _ref_cache.get(state)
    if cached and time.monotonic() - cached[0] < REF_DATA_TTL_SECONDS:
        return cached[1]
    data = await _call("GET", REF_DATA_PATH, params={"states": state})
    _ref_cache[state] = (time.monotonic(), data)
    return data


def _items(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return (data.get(key) or {}).get("items") or []


def _station_summary(s: dict[str, Any]) -> dict[str, Any]:
    loc = s.get("location") or {}
    return {
        "station_code": str(s.get("code")),
        "name": s.get("name"),
        "brand": s.get("brand"),
        "address": s.get("address"),
        "latitude": loc.get("latitude"),
        "longitude": loc.get("longitude"),
        "state": s.get("state"),
    }


def _resolve_location(stations: list[dict[str, Any]], location: str) -> tuple[float, float]:
    """교외명(suburb) 또는 우편번호를, 그 지역 주유소들의 평균 좌표로 바꾼다."""
    wanted = location.strip().upper()
    coords = []
    for s in stations:
        m = _ADDRESS_RE.search(s.get("address") or "")
        if not m or wanted not in (m.group(1).upper(), m.group(2)):
            continue
        loc = s.get("location") or {}
        if loc.get("latitude") is not None and loc.get("longitude") is not None:
            coords.append((float(loc["latitude"]), float(loc["longitude"])))
    if not coords:
        raise ToolError(
            f"Could not find location '{location}'. Use an exact suburb name or 4-digit postcode, "
            "or pass latitude/longitude instead."
        )
    return (
        sum(c[0] for c in coords) / len(coords),
        sum(c[1] for c in coords) / len(coords),
    )


@mcp.tool(annotations=READ_ONLY)
async def list_fuel_types(state: State = "NSW") -> list[dict[str, str]]:
    """List fuel type codes and names (e.g. U91 = Unleaded 91, E10, P98, DL = Diesel)."""
    data = await _ref_data(state)
    return [{"code": f["code"], "name": f["name"]} for f in _items(data, "fueltypes")]


@mcp.tool(annotations=READ_ONLY)
async def search_stations(query: str, state: State = "NSW", limit: int = 10) -> list[dict[str, Any]]:
    """Search stations by name, brand or address (incl. suburb/postcode). Use the returned station_code with get_station_prices."""
    terms = query.lower().split()
    data = await _ref_data(state)
    results = []
    for s in _items(data, "stations"):
        haystack = f"{s.get('name', '')} {s.get('brand', '')} {s.get('address', '')}".lower()
        if all(t in haystack for t in terms):
            results.append(_station_summary(s))
            if len(results) >= limit:
                break
    return results


@mcp.tool(annotations=READ_ONLY)
async def get_station_prices(station_code: str, state: State = "NSW") -> list[dict[str, Any]]:
    """Current prices (cents/L) for every fuel type at one station."""
    data = await _call("GET", f"{PRICES_PATH}/station/{station_code}", params={"states": state})
    return [
        {"fuel_type": p.get("fueltype"), "price": p.get("price"), "last_updated": p.get("lastupdated")}
        for p in data.get("prices") or []
    ]


@mcp.tool(annotations=READ_ONLY)
async def find_fuel_prices(
    fuel_type: str,
    location: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = 5,
    brands: list[str] | None = None,
    sort_by: Literal["price", "distance"] = "price",
    limit: int = 10,
    state: State = "NSW",
) -> list[dict[str, Any]]:
    """Find prices (cents/L) for one fuel type at stations near a location.

    Give either location (suburb or postcode, e.g. "Redfern", "2016") or latitude/longitude.
    fuel_type is a code from list_fuel_types (e.g. "U91", "E10", "DL").
    """
    if latitude is None or longitude is None:
        if not location:
            raise ToolError("Provide either location or latitude/longitude.")
        latitude, longitude = _resolve_location(_items(await _ref_data(state), "stations"), location)

    body: dict[str, Any] = {
        "fueltype": fuel_type.upper(),
        "latitude": str(latitude),
        "longitude": str(longitude),
        "radius": str(radius_km),
        "sortby": sort_by,
        "sortascending": "true",
    }
    if brands:
        body["brand"] = brands
    data = await _call("POST", f"{PRICES_PATH}/nearby", json=body)

    stations = {str(s.get("code")): s for s in data.get("stations") or []}
    results = []
    for p in data.get("prices") or []:
        s = stations.get(str(p.get("stationcode")), {})
        loc = s.get("location") or {}
        results.append(
            {
                "station_code": str(p.get("stationcode")),
                "name": s.get("name"),
                "brand": s.get("brand"),
                "address": s.get("address"),
                "distance_km": loc.get("distance"),
                "fuel_type": p.get("fueltype"),
                "price": p.get("price"),
                "last_updated": p.get("lastupdated"),
            }
        )
    sort_key = "price" if sort_by == "price" else "distance_km"
    results.sort(key=lambda r: (r[sort_key] is None, r[sort_key] or 0))
    return results[:limit]


def run() -> None:
    # httpx 가 요청마다 INFO 로그를 남겨서 MCP 클라이언트 로그가 지저분해진다.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run()
