"""Place lookup via the TfNSW Trip Planner stop finder, shared by servers that take place names.

Never guess: if several candidates match about equally well, raise with the candidates so the caller can choose.
"""

from __future__ import annotations

import re
from typing import Any

from .client import ApiNswError
from .tfnsw import TfnswClient

TP_PATH = "/v1/tp"
TP_PARAMS = {"outputFormat": "rapidJSON", "coordOutputFormat": "EPSG:4326", "version": "10.2.1.42"}

# A place name is ambiguous when another candidate of the same type scores within 1% of the best.
# Measured: "UNSW" 976 vs 975, "Parramatta" station 985 vs wharf 981 (ambiguous);
# "Central" 987 vs Adelaide 975, "Opera House" 241 vs 235 (clear).
AMBIGUITY_RATIO = 0.99

# "lat,lng" input such as "-33.91, 151.23"
_COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def parse_coords(value: str) -> tuple[float, float] | None:
    m = _COORD_RE.match(value)
    return (float(m.group(1)), float(m.group(2))) if m else None


def best_location(locations: list[dict[str, Any]]) -> dict[str, Any] | None:
    best = [loc for loc in locations if loc.get("isBest")]
    if best:
        return best[0]
    return max(locations, key=lambda loc: loc.get("matchQuality", 0), default=None)


def _normalize(name: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", name.lower()).split())


def _close_rivals(locations: list[dict[str, Any]], best: dict[str, Any]) -> list[dict[str, Any]]:
    """Other candidates of the same type whose score is too close to the best one to pick safely.

    Scores are on different scales per type (stops ~1000, streets/POIs ~250), so only compare within a type.
    """
    floor = best.get("matchQuality", 0) * AMBIGUITY_RATIO
    return [
        loc
        for loc in locations
        if loc is not best and loc.get("type") == best.get("type") and loc.get("matchQuality", 0) >= floor
    ]


async def stop_finder(client: TfnswClient, query: str) -> list[dict[str, Any]]:
    # type_sf=stop only works for exact names ("stop invalid"), so always search with any and filter.
    data = await client.get(f"{TP_PATH}/stop_finder", {**TP_PARAMS, "type_sf": "any", "name_sf": query, "TfNSWSF": "true"})
    return data.get("locations") or []


async def resolve_place(client: TfnswClient, place: str, *, stops_only: bool = False) -> dict[str, Any]:
    """Resolve a place name, stop ID or 'lat,lng' to one location.

    Returns type/name (as the Trip Planner accepts them), a readable label, stop_id, and latitude/longitude.
    """
    coords = parse_coords(place)
    if coords and not stops_only:
        lat, lng = coords
        return {
            "type": "coord",
            "name": f"{lng}:{lat}:EPSG:4326",
            "label": f"{lat},{lng}",
            "stop_id": None,
            "latitude": lat,
            "longitude": lng,
        }

    locations = await stop_finder(client, place)
    if stops_only:
        locations = [loc for loc in locations if loc.get("type") == "stop"]
    loc = best_location(locations)
    if not loc:
        kind = "stop" if stops_only else "place"
        raise ApiNswError(f"Could not find a {kind} matching '{place}'. Try a more specific name.")

    exact = [l for l in locations if _normalize(l.get("name") or "") == _normalize(place)]
    if exact:
        loc = exact[0]
    elif rivals := _close_rivals(locations, loc):
        options = "; ".join(f"{c.get('name')} (id {c.get('id')})" for c in [loc, *rivals][:5])
        raise ApiNswError(
            f"'{place}' is ambiguous. Candidates: {options}. "
            "Ask the user which one they mean, or call again with the chosen id."
        )
    coord = loc.get("coord") or [None, None]
    return {
        "type": "any",
        "name": loc["id"],
        "label": loc.get("name"),
        "stop_id": (loc.get("properties") or {}).get("stopId"),
        "latitude": coord[0],
        "longitude": coord[1],
    }
