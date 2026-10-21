"""NSW roads MCP server (TfNSW Live Traffic Hazards and Toll Calculator APIs).

Required environment variable: NSW_TRANSPORT_API_KEY (TfNSW Open Data Hub key, same as the transport server).
Hazard feeds are large (the regional feed alone is ~1 MB), so tools filter by area or distance and return
trimmed summaries. Timestamps are converted to Sydney local time.
"""

from __future__ import annotations

import html
import logging
import math
import re
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from mcp_au_nsw.core import ApiNswError, TfnswClient, client_from_env, resolve_place

SYDNEY = ZoneInfo("Australia/Sydney")
HAZARDS_PATH = "/v1/live/hazards"
TOLL_ROUTE_PATH = "/v2/roads/toll_calc/route"

# Tool-facing category names -> hazard feed paths
HAZARD_FEEDS = {
    "incident": "incident",
    "roadwork": "roadwork",
    "fire": "fire",
    "flood": "flood",
    "alpine": "alpine",
    "major_event": "majorevent",
    "regional_incident": "regional-lga-incident",
}
HazardCategory = Literal["incident", "roadwork", "fire", "flood", "alpine", "major_event", "regional_incident"]

# Toll Calculator vehicle classes: A = cars and motorcycles, B = heavy vehicles
VEHICLE_CLASSES = {"car": "A", "truck": "B"}

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

mcp = MCPServer(
    name="nsw-roads",
    instructions=(
        "NSW road conditions and tolls from Transport for NSW. Use get_traffic_hazards for crashes, roadworks, "
        "floods, fires, alpine conditions and major events (filter by area or distance from a place). "
        "Use calculate_toll for toll costs between two places, optionally compared with a toll-free route. "
        "Places can be given as names, addresses or 'lat,lng'. All times are Sydney local time."
    ),
)

_client: TfnswClient | None = None


def _get_client() -> TfnswClient:
    global _client
    if _client is None:
        try:
            _client = client_from_env()
        except ApiNswError as e:
            raise ToolError(str(e)) from e
    return _client


async def _call(method: str, path: str, **kwargs: Any) -> Any:
    try:
        return await _get_client().request(method, path, **kwargs)
    except ApiNswError as e:
        raise ToolError(str(e)) from e


async def _resolve(place: str) -> dict[str, Any]:
    try:
        return await resolve_place(_get_client(), place)
    except ApiNswError as e:
        raise ToolError(str(e)) from e


def _from_epoch_ms(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, SYDNEY).strftime("%Y-%m-%d %H:%M")


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(text).split())


def _distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance (haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _describe_road(road: dict[str, Any]) -> str:
    """'Putty Road between Colo Heights and Mellong, Colo Heights (Sydney)'."""
    main = (road.get("mainStreet") or "").strip()
    cross = (road.get("crossStreet") or "").strip()
    second = (road.get("secondLocation") or "").strip()
    desc = main
    if cross:
        desc += f" {(road.get('locationQualifier') or 'at').strip()} {cross}"
    if second:
        desc += f" and {second}"
    place = ", ".join(x for x in [(road.get("suburb") or "").strip()] if x)
    region = (road.get("region") or "").strip()
    if region:
        place = f"{place} ({region})" if place else region
    return ", ".join(x for x in [desc, place] if x)


def _describe_period(period: dict[str, Any]) -> str:
    """'Weekdays 7:00am-5:00pm, Both directions, Affected'."""
    days = " to ".join(x for x in [period.get("fromDay"), period.get("toDay")] if x)
    start, finish = period.get("startTime") or "", period.get("finishTime") or ""
    hours = f"{start}-{finish}" if start and finish else start or finish
    parts = [" ".join(x for x in [days, hours] if x), period.get("direction"), period.get("roadextent")]
    return ", ".join(x for x in parts if x)


def _hazard_text(props: dict[str, Any]) -> str:
    """All searchable location text for the area filter."""
    fields = ("suburb", "region", "mainStreet", "crossStreet", "secondLocation")
    roads = " ".join(str(road.get(f) or "") for road in props.get("roads") or [] for f in fields)
    return f"{roads} {props.get('displayName') or ''}".lower()


def _hazard_summary(feature: dict[str, Any], category: str) -> dict[str, Any]:
    props = feature.get("properties") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or [None, None]
    roads = props.get("roads") or []
    advice = [a.strip() for a in (props.get("adviceA"), props.get("adviceB"), props.get("adviceC")) if a and a.strip()]
    summary: dict[str, Any] = {
        "id": feature.get("id"),
        "category": category,
        "type": props.get("mainCategory"),
        "title": props.get("displayName") or props.get("headline"),
        "planned": props.get("incidentKind") == "Planned",
        "major": bool(props.get("isMajor")),
        "location": _describe_road(roads[0]) if roads else None,
        "other_roads": [_describe_road(r) for r in roads[1:]],
        "advice": advice,
        "details": _strip_html(props.get("otherAdvice"))[:800],
        "public_transport": _strip_html(props.get("publicTransport"))[:800],
        "diversions": _strip_html(props.get("diversions"))[:800],
        "schedule": [_describe_period(p) for p in props.get("periods") or []],
        "expected_delay_min": props.get("expectedDelay") if (props.get("expectedDelay") or -1) >= 0 else None,
        "start": _from_epoch_ms(props.get("start")),
        "end": _from_epoch_ms(props.get("end")),
        "last_updated": _from_epoch_ms(props.get("lastUpdated")),
        "ended": bool(props.get("ended")),
        # GeoJSON order is [longitude, latitude]
        "latitude": coords[1],
        "longitude": coords[0],
        "links": [link.get("linkURL") for link in props.get("webLinks") or [] if link.get("linkURL")],
    }
    return summary


@mcp.tool(annotations=READ_ONLY)
async def get_traffic_hazards(
    categories: list[HazardCategory] | None = None,
    area: str | None = None,
    near: str | None = None,
    radius_km: float = 10,
    include_ended: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    """Live Traffic NSW hazards: crashes, breakdowns, roadworks, floods, fires, alpine conditions and major events.

    categories: which feeds to read (default: all). area: text matched against suburb, region and road names
    (e.g. "Parramatta", "M4", "Blue Mountains"). near: a place name, address or 'lat,lng'; only hazards within
    radius_km are returned, nearest first. include_ended: also return hazards that have finished.
    Open roadworks and events include planned ones that haven't started yet; check `start`.
    """
    center = None
    if near:
        place = await _resolve(near)
        center = (place["latitude"], place["longitude"], place["label"])

    feeds = categories or list(HAZARD_FEEDS)
    status = "all" if include_ended else "open"
    wanted_area = area.strip().lower() if area else None

    hazards = []
    for category in feeds:
        data = await _call("GET", f"{HAZARDS_PATH}/{HAZARD_FEEDS[category]}/{status}")
        for feature in data.get("features") or []:
            props = feature.get("properties") or {}
            if wanted_area and wanted_area not in _hazard_text(props):
                continue
            summary = _hazard_summary(feature, category)
            if center:
                if summary["latitude"] is None or summary["longitude"] is None:
                    continue
                dist = _distance_km(center[0], center[1], summary["latitude"], summary["longitude"])
                if dist > radius_km:
                    continue
                summary["distance_km"] = round(dist, 1)
            hazards.append(summary)

    if center:
        hazards.sort(key=lambda h: h["distance_km"])
    else:
        # Major and unplanned first; within each group, most recently updated first (sorts are stable).
        hazards.sort(key=lambda h: h["last_updated"] or "", reverse=True)
        hazards.sort(key=lambda h: (not h["major"], h["planned"]))
    return {
        "near": center[2] if center else None,
        "total_matched": len(hazards),
        "hazards": hazards[:limit],
    }


def _route_summary(route: dict[str, Any]) -> dict[str, Any]:
    tolls = []
    for toll in route.get("tollsCharged") or []:
        visits = toll.get("gantryVisits") or []
        gantries = [v.get("gantry") or {} for v in visits]
        tolls.append(
            {
                "motorway": gantries[0].get("motorwayName") if gantries else None,
                "entry": gantries[0].get("gantryName") if gantries else None,
                "exit": gantries[-1].get("gantryName") if gantries else None,
                "provider": gantries[0].get("motorwayProvider") if gantries else None,
                "min_charge_aud": round((toll.get("minChargeInCents") or 0) / 100, 2),
                "max_charge_aud": round((toll.get("maxChargeInCents") or 0) / 100, 2),
            }
        )
    return {
        "via": route.get("summary"),
        "distance_km": round((route.get("distance") or 0) / 1000, 1),
        "duration_min": round((route.get("duration") or 0) / 60),
        "min_toll_aud": round((route.get("minChargeInCents") or 0) / 100, 2),
        "max_toll_aud": round((route.get("maxChargeInCents") or 0) / 100, 2),
        "cheapest": bool(route.get("isCheapest")),
        "quickest": bool(route.get("isQuickest")),
        "shortest": bool(route.get("isShortest")),
        "tolls": tolls,
    }


@mcp.tool(annotations=READ_ONLY)
async def calculate_toll(
    origin: str,
    destination: str,
    when: str | None = None,
    vehicle: Literal["car", "truck"] = "car",
    compare_toll_free: bool = True,
) -> dict[str, Any]:
    """Estimate toll costs (AUD) for driving between two places in NSW, with the toll roads used.

    origin/destination: a place name, address or 'lat,lng'. when: 'YYYY-MM-DD HH:MM' Sydney time (tolls vary by
    time of day); default now. vehicle: "car" (class A, incl. motorcycles) or "truck" (class B).
    compare_toll_free: also return the quickest toll-free route so the time saved can be weighed against the cost.
    Results are estimates from Transport for NSW and may differ from what is actually charged.
    """
    o = await _resolve(origin)
    d = await _resolve(destination)
    if when:
        try:
            departure = datetime.strptime(when.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=SYDNEY)
        except ValueError as e:
            raise ToolError("when must be 'YYYY-MM-DD HH:MM' (Sydney time).") from e
    else:
        departure = datetime.now(SYDNEY)

    body: dict[str, Any] = {
        "origin": {"lat": o["latitude"], "lng": o["longitude"]},
        "destination": {"lat": d["latitude"], "lng": d["longitude"]},
        "departureTime": departure.isoformat(timespec="seconds"),
        "vehicleClass": VEHICLE_CLASSES[vehicle],
    }
    data = await _call("POST", TOLL_ROUTE_PATH, json=body)
    routes = [_route_summary(r) for r in data.get("routes") or []]
    if not routes:
        raise ToolError(f"No driving route found from '{o['label']}' to '{d['label']}'.")

    result: dict[str, Any] = {
        "from": o["label"],
        "to": d["label"],
        "departure": departure.strftime("%Y-%m-%d %H:%M"),
        "vehicle": vehicle,
        "routes": routes,
    }
    if compare_toll_free:
        free = await _call("POST", TOLL_ROUTE_PATH, json={**body, "excludeToll": True})
        free_routes = [_route_summary(r) for r in free.get("routes") or []]
        if free_routes:
            quickest_free = min(free_routes, key=lambda r: r["duration_min"])
            quickest_free.pop("tolls", None)
            result["toll_free_alternative"] = quickest_free
            result["minutes_saved_by_tolls"] = quickest_free["duration_min"] - min(r["duration_min"] for r in routes)
    return result


def run() -> None:
    # httpx logs every request at INFO, which clutters MCP client logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run()
