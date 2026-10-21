import httpx
import pytest
import respx

from mcp_au_nsw.core import ApiNswClient, ApiNswError

BASE = "https://api.onegov.nsw.gov.au"
TOKEN_URL = f"{BASE}/oauth/client_credential/accesstoken"


def _token(value="tok-1"):
    return httpx.Response(200, json={"access_token": value, "expires_in": "43199"})


@respx.mock
async def test_token_is_cached_between_requests():
    token_route = respx.get(TOKEN_URL).mock(return_value=_token())
    data_route = respx.get(f"{BASE}/x").mock(return_value=httpx.Response(200, json={"ok": True}))

    client = ApiNswClient("key", "secret")
    assert await client.request("GET", "/x") == {"ok": True}
    assert await client.request("GET", "/x") == {"ok": True}

    assert token_route.call_count == 1
    headers = data_route.calls[0].request.headers
    assert headers["Authorization"] == "Bearer tok-1"
    assert headers["apikey"] == "key"
    assert headers["transactionid"] != data_route.calls[1].request.headers["transactionid"]


@respx.mock
async def test_401_refreshes_token_once():
    respx.get(TOKEN_URL).mock(side_effect=[_token("old"), _token("new")])
    respx.get(f"{BASE}/x").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={"ok": True})]
    )

    client = ApiNswClient("key", "secret")
    assert await client.request("GET", "/x") == {"ok": True}


@respx.mock
async def test_error_details_are_surfaced():
    respx.get(TOKEN_URL).mock(return_value=_token())
    respx.get(f"{BASE}/x").mock(
        return_value=httpx.Response(
            200, json={"errorDetails": [{"code": "E0001", "description": "State not supported"}]}
        )
    )

    client = ApiNswClient("key", "secret")
    with pytest.raises(ApiNswError, match="E0001 State not supported"):
        await client.request("GET", "/x")


@respx.mock
async def test_bad_credentials():
    respx.get(TOKEN_URL).mock(return_value=httpx.Response(401))
    client = ApiNswClient("key", "wrong")
    with pytest.raises(ApiNswError, match="token request failed"):
        await client.request("GET", "/x")
