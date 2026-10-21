import httpx
import pytest
import respx
from mcp.server.mcpserver.exceptions import ToolError

from mcp_au_nsw.core import TfnswClient
from mcp_au_nsw.transport import server
from mcp_au_nsw.core import places
from mcp_au_nsw.core.places import best_location
from mcp_au_nsw.transport.server import (
    _delay_minutes,
    _exclude_modes_params,
    _leg_summary,
    _local,
    _minutes_between,
    _when_params,
)


def test_local_converts_utc_to_sydney():
    # 22 October is daylight saving time (AEDT, UTC+11)
    assert _local("2026-10-21T21:45:00Z") == "2026-10-22 08:45"
    assert _local(None) is None


def test_delay_and_duration():
    assert _delay_minutes("2026-10-21T21:36:00Z", "2026-10-21T22:04:54Z") == 29
    assert _delay_minutes("2026-10-21T21:36:00Z", None) is None
    assert _minutes_between("2026-10-22 23:50", "2026-10-23 00:10") == 20


def test_when_params():
    assert _when_params("2026-12-25 07:05") == {"itdDate": "20261225", "itdTime": "0705"}
    assert _when_params("17:30")["itdTime"] == "1730"
    with pytest.raises(ToolError):
        _when_params("tomorrow")


def test_exclude_modes_keeps_only_requested():
    params = _exclude_modes_params(["train"])
    assert params["excludedMeans"] == "checkbox"
    assert "exclMOT_1" not in params
    assert params["exclMOT_5"] == "1"
    assert _exclude_modes_params(None) == {}


def test_best_location_prefers_is_best_then_quality():
    assert best_location([{"id": "a", "matchQuality": 900}, {"id": "b", "isBest": True}])["id"] == "b"
    assert best_location([{"id": "a", "matchQuality": 1}, {"id": "b", "matchQuality": 5}])["id"] == "b"
    assert best_location([]) is None


def _stop(id, name, quality, type="stop", best=False):
    return {"id": id, "name": name, "type": type, "matchQuality": quality, "isBest": best}


def _fake_stop_finder(monkeypatch, locations):
    async def fake(client, query):
        return locations

    monkeypatch.setattr(places, "stop_finder", fake)
    monkeypatch.setattr(server, "_client", TfnswClient("key"))


async def test_resolve_refuses_to_guess_between_close_candidates(monkeypatch):
    _fake_stop_finder(
        monkeypatch,
        [
            _stop("2031156", "UNSW High Street Light Rail, Randwick", 976, best=True),
            _stop("203360", "UNSW Anzac Parade Light Rail, Kensington", 975),
            _stop("poi1", "UNSW, Randwick", 250, type="poi"),
        ],
    )
    with pytest.raises(ToolError, match="ambiguous.*2031156.*203360"):
        await server._resolve("UNSW")


async def test_resolve_picks_clear_winner(monkeypatch):
    _fake_stop_finder(
        monkeypatch,
        [
            _stop("200060", "Central Station, Sydney", 987, best=True),
            _stop("G50001", "Adelaide Central Bus Station", 975),
        ],
    )
    assert (await server._resolve("Central"))["name"] == "200060"


async def test_resolve_prefers_exact_name_match(monkeypatch):
    _fake_stop_finder(
        monkeypatch,
        [
            _stop("addr17", "17 High St, Kensington", 250, type="singlehouse", best=True),
            _stop("addr15", "15-17 High St, Kensington", 247, type="singlehouse"),
        ],
    )
    assert (await server._resolve("17 High St Kensington"))["name"] == "addr17"


def test_walk_leg_summary():
    leg = {
        "duration": 540,
        "distance": 587,
        "transportation": {"product": {"class": 100}},
        "origin": {"name": "A", "departureTimePlanned": "2026-10-21T21:49:30Z"},
        "destination": {"name": "B", "arrivalTimePlanned": "2026-10-21T21:58:30Z"},
    }
    s = _leg_summary(leg)
    assert s["mode"] == "walk" and s["distance_m"] == 587 and "line" not in s


@respx.mock
async def test_client_retries_after_429(monkeypatch):
    monkeypatch.setattr("mcp_au_nsw.core.tfnsw.RETRY_DELAYS_SECONDS", (0, 0))
    route = respx.get("https://api.transport.nsw.gov.au/x").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json={"ok": True})]
    )
    client = TfnswClient("key")
    assert await client.get("/x") == {"ok": True}
    assert route.calls[0].request.headers["Authorization"] == "apikey key"


async def test_missing_key(monkeypatch):
    monkeypatch.delenv("NSW_TRANSPORT_API_KEY", raising=False)
    monkeypatch.setattr(server, "_client", None)
    with pytest.raises(ToolError, match="NSW_TRANSPORT_API_KEY"):
        server._get_client()


def test_lists_line_matches_code_prefix_only():
    from mcp_au_nsw.transport.server import _lists_line

    assert _lists_line(["T1 North Shore & Western Line"], "T1")
    assert not _lists_line(["T10 Something"], "T1")
    assert not _lists_line([], "T1")


def _fake_alerts(monkeypatch, infos):
    async def fake(endpoint, **params):
        fake.params = params
        return {"infos": {"current": infos}}

    monkeypatch.setattr(server, "_tp", fake)
    return fake


def _info(id, *lines):
    return {"id": id, "priority": "normal", "affected": {"lines": [{"number": ln} for ln in lines]}}


async def test_alerts_send_uppercased_line_to_api(monkeypatch):
    fake = _fake_alerts(monkeypatch, [_info("a", "T1 North Shore & Western Line")])
    alerts = await server.get_service_alerts(line="t1")
    assert fake.params["itdLPxx_selLine"] == "T1"
    assert [a["id"] for a in alerts] == ["a"]


async def test_alerts_reject_unknown_line_instead_of_returning_everything(monkeypatch):
    _fake_alerts(monkeypatch, [_info("a", "T1 North Shore"), _info("b", "333")])
    with pytest.raises(ToolError, match="not recognised"):
        await server.get_service_alerts(line="XYZ999")


async def test_alerts_valid_line_with_no_alerts_is_empty(monkeypatch):
    _fake_alerts(monkeypatch, [])
    assert await server.get_service_alerts(line="392X") == []
