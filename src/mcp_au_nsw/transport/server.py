"""NSW public transport MCP server (TfNSW Trip Planner API).

Required environment variable: NSW_TRANSPORT_API_KEY (TfNSW Open Data Hub key)
Trip Planner responses are very verbose (tens of KB per journey), so tools return only the fields that matter.
Response times are UTC and are all converted to Sydney local time.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from mcp_au_nsw.core import ApiNswError, TfnswClient, client_from_env, resolve_place
from mcp_au_nsw.core.places import TP_PARAMS

SYDNEY = ZoneInfo("Australia/Sydney")
TP_PATH = "/v1/tp"

# Trip Planner product class codes -> readable names
MODE_NAMES = {
    1: "train",
    2: "metro",
    4: "light_rail",
    5: "bus",
    7: "coach",
    9: "ferry",
    11: "school_bus",
    99: "walk",
    100: "walk",
}
Mode = Literal["train", "metro", "light_rail", "bus", "coach", "ferry", "school_bus"]
MODE_CODES = {name: code for code, name in MODE_NAMES.items() if name != "walk"}

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

mcp = MCPServer(
    name="nsw-transport",
    instructions=(
        "NSW public transport (trains, metro, buses, light rail, ferries) from the Transport for NSW trip planner. "
        "Places can be given as names (stations, stops, addresses, landmarks), stop IDs, or 'lat,lng'. "
        "All times are Sydney local time. Use plan_trip for A-to-B journeys, get_departures for the next "
        "services from a stop, and get_service_alerts for disruptions and trackwork."
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


async def _tp(endpoint: str, **params: Any) -> dict[str, Any]:
    try:
        return await _get_client().get(f"{TP_PATH}/{endpoint}", {**TP_PARAMS, **params})
    except ApiNswError as e:
        raise ToolError(str(e)) from e


def _local(ts: str | None) -> str | None:
    """'2026-10-21T21:45:00Z' -> '2026-10-22 08:45' (Sydney time)."""
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(SYDNEY).strftime("%Y-%m-%d %H:%M")


def _delay_minutes(planned: str | None, estimated: str | None) -> int | None:
    if not planned or not estimated:
        return None
    p = datetime.fromisoformat(planned.replace("Z", "+00:00"))
    e = datetime.fromisoformat(estimated.replace("Z", "+00:00"))
    return round((e - p).total_seconds() / 60)


def _minutes_between(start: str | None, end: str | None) -> int | None:
    """Minutes between two times in _local() format."""
    if not start or not end:
        return None
    fmt = "%Y-%m-%d %H:%M"
    return round((datetime.strptime(end, fmt) - datetime.strptime(start, fmt)).total_seconds() / 60)


def _when_params(when: str | None) -> dict[str, str]:
    """'HH:MM' or 'YYYY-MM-DD HH:MM' (Sydney time) -> itdDate/itdTime. Defaults to now."""
    now = datetime.now(SYDNEY)
    if not when:
        dt = now
    else:
        try:
            if len(when.strip()) <= 5:
                t = datetime.strptime(when.strip(), "%H:%M")
                dt = now.replace(hour=t.hour, minute=t.minute)
            else:
                dt = datetime.strptime(when.strip(), "%Y-%m-%d %H:%M")
        except ValueError as e:
            raise ToolError("Time must be 'HH:MM' or 'YYYY-MM-DD HH:MM' (Sydney time).") from e
    return {"itdDate": dt.strftime("%Y%m%d"), "itdTime": dt.strftime("%H%M")}


def _exclude_modes_params(modes: list[Mode] | None) -> dict[str, str]:
    """Trip Planner params that exclude every mode not in `modes`."""
    if not modes:
        return {}
    wanted = {MODE_CODES[m] for m in modes}
    params = {"excludedMeans": "checkbox"}
    for code in set(MODE_CODES.values()) - wanted:
        params[f"exclMOT_{code}"] = "1"
    return params


async def _resolve(place: str, *, stops_only: bool = False) -> dict[str, Any]:
    try:
        return await resolve_place(_get_client(), place, stops_only=stops_only)
    except ApiNswError as e:
        raise ToolError(str(e)) from e


def _mode_of(transportation: dict[str, Any]) -> str:
    cls = (transportation.get("product") or {}).get("class")
    return MODE_NAMES.get(cls, "other")


def _platform(point: dict[str, Any]) -> str | None:
    return (point.get("properties") or {}).get("platformName")


def _leg_summary(leg: dict[str, Any]) -> dict[str, Any]:
    t = leg.get("transportation") or {}
    o, d = leg.get("origin") or {}, leg.get("destination") or {}
    mode = _mode_of(t)
    summary: dict[str, Any] = {
        "mode": mode,
        "from": o.get("name"),
        "to": d.get("name"),
        "depart": _local(o.get("departureTimeEstimated") or o.get("departureTimePlanned")),
        "arrive": _local(d.get("arrivalTimeEstimated") or d.get("arrivalTimePlanned")),
        "duration_min": round((leg.get("duration") or 0) / 60),
    }
    if mode == "walk":
        summary["distance_m"] = leg.get("distance")
        return summary
    summary.update(
        {
            "line": t.get("disassembledName") or t.get("number"),
            "towards": (t.get("destination") or {}).get("name"),
            "platform": _platform(o),
            "delay_min": _delay_minutes(o.get("departureTimePlanned"), o.get("departureTimeEstimated")),
            "realtime": bool(leg.get("isRealtimeControlled")),
        }
    )
    alerts = [i.get("subtitle") for i in leg.get("infos") or [] if i.get("subtitle")]
    if alerts:
        summary["alerts"] = alerts
    return summary


@mcp.tool(annotations=READ_ONLY)
async def find_stops(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search train stations, bus stops, wharves and light rail stops by name. Returns stop IDs and the modes served."""
    # type_sf=stop only works for exact names, so search with any and keep the stops.
    data = await _tp("stop_finder", type_sf="any", name_sf=query, TfNSWSF="true")
    stops = [loc for loc in data.get("locations") or [] if loc.get("type") == "stop"]
    locations = sorted(stops, key=lambda loc: -loc.get("matchQuality", 0))
    return [
        {
            "stop_id": loc.get("id"),
            "name": loc.get("name"),
            "modes": sorted({MODE_NAMES.get(m, "other") for m in loc.get("modes") or []}),
            "latitude": (loc.get("coord") or [None, None])[0],
            "longitude": (loc.get("coord") or [None, None])[1],
        }
        for loc in locations[:limit]
    ]


@mcp.tool(annotations=READ_ONLY)
async def get_departures(
    stop: str,
    modes: list[Mode] | None = None,
    when: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Next departures from a station or stop, with real-time delays and platforms.

    stop: a stop name (e.g. "Town Hall Station") or stop ID from find_stops.
    modes: only include these modes (e.g. ["train"]). when: 'HH:MM' or 'YYYY-MM-DD HH:MM' Sydney time; default now.
    """
    place = await _resolve(stop, stops_only=True)
    data = await _tp(
        "departure_mon",
        mode="direct",
        type_dm="any",
        name_dm=place["name"],
        depArrMacro="dep",
        TfNSWDM="true",
        **_when_params(when),
        **_exclude_modes_params(modes),
    )
    events = []
    for ev in data.get("stopEvents") or []:
        t = ev.get("transportation") or {}
        planned, estimated = ev.get("departureTimePlanned"), ev.get("departureTimeEstimated")
        events.append(
            {
                "departs": _local(estimated or planned),
                "scheduled": _local(planned),
                "delay_min": _delay_minutes(planned, estimated),
                "realtime": bool(ev.get("isRealtimeControlled")),
                "mode": _mode_of(t),
                "line": t.get("disassembledName") or t.get("number"),
                "destination": (t.get("destination") or {}).get("name"),
                "platform": _platform(ev.get("location") or {}),
            }
        )
    events.sort(key=lambda e: e["departs"] or "")
    return {"stop": place["label"], "departures": events[:limit]}


@mcp.tool(annotations=READ_ONLY)
async def plan_trip(
    origin: str,
    destination: str,
    when: str | None = None,
    arrive_by: bool = False,
    modes: list[Mode] | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Plan a public transport journey from A to B, using real-time data where available.

    origin/destination: a place name (station, address, landmark like "UNSW"), stop ID, or 'lat,lng'.
    when: 'HH:MM' or 'YYYY-MM-DD HH:MM' Sydney time; default now. arrive_by: treat `when` as the arrival deadline.
    modes: only use these modes (walking is always allowed).
    """
    o = await _resolve(origin)
    d = await _resolve(destination)
    data = await _tp(
        "trip",
        type_origin=o["type"],
        name_origin=o["name"],
        type_destination=d["type"],
        name_destination=d["name"],
        depArrMacro="arr" if arrive_by else "dep",
        calcNumberOfTrips=str(max(limit, 1)),
        TfNSWTR="true",
        **_when_params(when),
        **_exclude_modes_params(modes),
    )
    journeys = []
    for j in (data.get("journeys") or [])[:limit]:
        legs = [_leg_summary(leg) for leg in j.get("legs") or []]
        if not legs:
            continue
        journeys.append(
            {
                "depart": legs[0]["depart"],
                "arrive": legs[-1]["arrive"],
                # Summing leg durations misses interchange waits, so use the departure/arrival times.
                "duration_min": _minutes_between(legs[0]["depart"], legs[-1]["arrive"]),
                "interchanges": j.get("interchanges"),
                "legs": legs,
            }
        )
    if not journeys:
        raise ToolError(f"No journeys found from '{o['label']}' to '{d['label']}' at that time.")
    return {"from": o["label"], "to": d["label"], "journeys": journeys}


@mcp.tool(annotations=READ_ONLY)
async def get_service_alerts(
    mode: Mode | None = None,
    line: str | None = None,
    stop: str | None = None,
    limit: int = 15,
) -> list[dict[str, Any]]:
    """Current disruptions, trackwork and service changes. Filter by mode, line (e.g. "T1", "L2", "333") and/or stop name.

    There are usually hundreds of current alerts, so always filter when you can.
    """
    params: dict[str, Any] = {"filterPublicationStatus": "current"}
    if mode:
        params["filterMOTType"] = str(MODE_CODES[mode])
    wanted_line = line.strip().upper() if line else None
    if wanted_line:
        # Case-sensitive on the API side: "t1" returns nothing, "T1" works.
        params["itdLPxx_selLine"] = wanted_line
    if stop:
        place = await _resolve(stop, stops_only=True)
        params["itdLPxx_selStop"] = place["stop_id"] or place["name"]
    data = await _tp("add_info", **params)
    infos = (data.get("infos") or {}).get("current") or []

    alerts = [_alert_summary(info) for info in infos]
    # An unknown line is silently ignored by the API, which then returns every alert. Valid lines always
    # come back with at least one alert listing that line, so if none do, the filter was not applied.
    if wanted_line and alerts and not any(_lists_line(a["lines"], wanted_line) for a in alerts):
        raise ToolError(
            f"Line '{line}' was not recognised. Use the line code as shown on services, e.g. T1, L2, M1, F1, 333."
        )
    alerts.sort(key=lambda a: PRIORITY_RANK.get(a["priority"], 9))
    return alerts[:limit]


PRIORITY_RANK = {"veryHigh": 0, "high": 1, "normal": 2, "low": 3, "veryLow": 4}


def _lists_line(lines: list[str], wanted: str) -> bool:
    """'T1 North Shore & Western Line' lists line 'T1'."""
    return any(ln.upper().split()[0] == wanted for ln in lines if ln.strip())


def _alert_summary(info: dict[str, Any]) -> dict[str, Any]:
    lines = [ln.get("disassembledName") or ln.get("number") for ln in (info.get("affected") or {}).get("lines") or []]
    link = (info.get("infoLinks") or [{}])[0]
    text = (info.get("properties") or {}).get("speechText") or link.get("speechText") or ""
    validity = ((info.get("timestamps") or {}).get("validity") or [{}])[0]
    return {
        "id": info.get("id"),
        "title": link.get("subtitle") or link.get("urlText"),
        "priority": info.get("priority"),
        "type": info.get("type"),
        "lines": sorted({ln for ln in lines if ln})[:10],
        "active_from": _local(validity.get("from")),
        # Open-ended alerts use a far-future end date (2500-12-31).
        "active_until": None if validity.get("isOpenEnd") else _local(validity.get("to")),
        "details": text[:600],
        "url": link.get("url"),
    }


def run() -> None:
    # httpx logs every request at INFO, which clutters MCP client logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run()
