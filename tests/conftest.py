import pytest


@pytest.fixture(autouse=True)
def no_rate_limit_waits(monkeypatch):
    """Clients space out requests to respect API rate limits; tests don't need to wait."""
    monkeypatch.setattr("mcp_au_nsw.core.client.MIN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr("mcp_au_nsw.core.client.RETRY_DELAYS_SECONDS", (0, 0))
    monkeypatch.setattr("mcp_au_nsw.core.tfnsw.MIN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr("mcp_au_nsw.core.tfnsw.RETRY_DELAYS_SECONDS", (0, 0))
