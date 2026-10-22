import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mcp_au_nsw.licences import server
from mcp_au_nsw.licences.server import REGISTERS, _business_names, _clean


def test_clean_normalises_without_losing_information():
    raw = {
        "expiryDate": "12/10/2027",
        "startDate": "N/A",
        "isActive": "True",
        "abn": "",
        "licenceName": None,
        "conditions": [],
        "count": 0,
        "associatedLicences": [{"licenceNumber": "43983S"}, {"licenceNumber": "43983S"}],
    }
    assert _clean(raw) == {
        "expiryDate": "2027-10-12",
        "isActive": True,
        "count": 0,
        "associatedLicences": [{"licenceNumber": "43983S"}],
    }


def test_business_names_handles_both_shapes():
    assert _business_names("Parkes Toyota") == ["Parkes Toyota"]
    assert _business_names([{"businessName": "Ray White Cabramatta"}]) == ["Ray White Cabramatta"]
    assert _business_names(None) == []


def test_every_register_has_a_tool_slug():
    slugs = set(server.RegisterSlug.__args__)
    assert slugs == set(REGISTERS)


def _fake_call(monkeypatch, response):
    async def fake(slug, endpoint, **params):
        fake.args = (slug, endpoint, params)
        return response

    monkeypatch.setattr(server, "_call", fake)
    return fake


async def test_verify_not_found_is_not_an_error(monkeypatch):
    _fake_call(monkeypatch, [])
    result = await server.verify_licence("trades", "000000000")
    assert result["found"] is False and "Trades register" in result["message"]


async def test_search_puts_current_first_and_flags_truncation(monkeypatch):
    rows = [{"licenceID": str(i), "status": "Expired" if i % 2 else "Current"} for i in range(200)]
    fake = _fake_call(monkeypatch, rows)
    result = await server.search_licences("property", "  Ray White ", limit=3)
    assert fake.args == ("property", "browse", {"searchText": "Ray White"})
    assert result["truncated"] is True
    assert [l["status"] for l in result["licences"]] == ["Current", "Current", "Current"]


async def test_unconfigured_register_explains_how_to_subscribe(monkeypatch):
    monkeypatch.delenv("NSW_LOTTERIES_API_KEY", raising=False)
    monkeypatch.setattr(server, "_clients", {})
    with pytest.raises(ToolError, match=r"NSW_LOTTERIES_API_KEY.*Product/Index/16"):
        server._get_client("lotteries")
