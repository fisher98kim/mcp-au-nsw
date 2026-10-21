import pytest

from mcp_au_nsw.roads.server import (
    _describe_period,
    _describe_road,
    _distance_km,
    _from_epoch_ms,
    _hazard_summary,
    _route_summary,
    _strip_html,
)


def test_from_epoch_ms_is_sydney_time():
    # 2026-10-21 21:45 UTC = 2026-10-22 08:45 AEDT
    assert _from_epoch_ms(1792619100000) == "2026-10-22 08:45"
    assert _from_epoch_ms(None) is None
    assert _from_epoch_ms(-1) is None


def test_strip_html():
    assert _strip_html("<p>Use <strong>Chifley Rd</strong> &amp; Darling Causeway.</p>") == "Use Chifley Rd & Darling Causeway."
    assert _strip_html(None) == ""


def test_describe_road_between():
    road = {
        "mainStreet": "Putty Road",
        "locationQualifier": "between",
        "crossStreet": "Colo Heights",
        "secondLocation": "Mellong",
        "suburb": "Colo Heights",
        "region": "Sydney",
    }
    assert _describe_road(road) == "Putty Road between Colo Heights and Mellong, Colo Heights (Sydney)"


def test_describe_period():
    period = {"fromDay": "Weekdays", "startTime": "7:00am", "finishTime": "5:00pm", "direction": "Both directions", "roadextent": "Affected"}
    assert _describe_period(period) == "Weekdays 7:00am-5:00pm, Both directions, Affected"


def test_distance_km():
    # Central Station to Circular Quay is about 2.6 km
    assert _distance_km(-33.8840, 151.2062, -33.8613, 151.2108) == pytest.approx(2.56, abs=0.1)


def test_hazard_summary_reads_geojson_lng_lat_order():
    feature = {
        "id": 1,
        "geometry": {"type": "Point", "coordinates": [151.0, -33.8]},
        "properties": {"displayName": "CRASH", "incidentKind": "Unplanned", "expectedDelay": -1, "roads": []},
    }
    s = _hazard_summary(feature, "incident")
    assert (s["latitude"], s["longitude"]) == (-33.8, 151.0)
    assert s["planned"] is False and s["expected_delay_min"] is None


def test_route_summary_converts_units():
    route = {
        "summary": "Western Motorway, M4 East Tunnel",
        "distance": 26730.9,
        "duration": 1702.6,
        "minChargeInCents": 1274,
        "maxChargeInCents": 1274,
        "isCheapest": True,
        "tollsCharged": [
            {
                "minChargeInCents": 1274,
                "maxChargeInCents": 1274,
                "gantryVisits": [
                    {"gantry": {"gantryName": "James Ruse Drive", "motorwayName": "WestConnex (M4, M5, M8)"}},
                    {"gantry": {"gantryName": "St Peters", "motorwayName": "WestConnex (M4, M5, M8)"}},
                ],
            }
        ],
    }
    s = _route_summary(route)
    assert s["distance_km"] == 26.7 and s["duration_min"] == 28 and s["min_toll_aud"] == 12.74
    assert s["tolls"][0]["entry"] == "James Ruse Drive" and s["tolls"][0]["exit"] == "St Peters"
