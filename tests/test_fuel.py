import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mcp_au_nsw.fuel.server import _resolve_location

STATIONS = [
    {"address": "411-417 Cleveland St, REDFERN NSW 2016", "location": {"latitude": -33.0, "longitude": 151.0}},
    {"address": "116 Regent Street, Redfern NSW 2016", "location": {"latitude": -34.0, "longitude": 152.0}},
    {"address": "61 COWPER WHARF ROADWAY, WOOLLOOMOOLOO NSW 2011", "location": {"latitude": -10.0, "longitude": 100.0}},
]


def test_resolve_by_suburb_is_case_insensitive_and_averages():
    assert _resolve_location(STATIONS, "redfern") == (-33.5, 151.5)


def test_resolve_by_postcode():
    assert _resolve_location(STATIONS, "2011") == (-10.0, 100.0)


def test_unknown_location():
    with pytest.raises(ToolError, match="Atlantis"):
        _resolve_location(STATIONS, "Atlantis")


def test_format_time_normalises_both_api_formats():
    from mcp_au_nsw.fuel.server import _format_time

    assert _format_time("19/10/2026 23:34:37") == "2026-10-19 23:34"
    assert _format_time("2026-10-20 04:22:54") == "2026-10-20 04:22"
    assert _format_time(None) is None
