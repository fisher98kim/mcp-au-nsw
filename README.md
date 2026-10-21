# mcp-au-nsw

[MCP](https://modelcontextprotocol.io) servers for NSW Government APIs on [api.nsw.gov.au](https://api.nsw.gov.au).
Ask Claude (or any MCP client) things like *"Where's the cheapest diesel near UNSW?"* and get live answers.

| Server | API | Status |
|---|---|---|
| `fuel` | [Fuel API](https://api.nsw.gov.au/Product/Index/22): live fuel prices for NSW & TAS | ✅ Available |

More API.NSW APIs (licence lookups and more) are planned.

## Quick start

### 1. Get an API key (free, ~5 minutes)

1. Sign up at [api.nsw.gov.au](https://api.nsw.gov.au).
2. Go to **My Apps → Add new app** and attach the **Fuel API**. (Each app can have only one API product.)
3. Copy the app's **API Key** and **API Secret**.

The free plan allows **2,500 calls per month**.

### 2. Install [uv](https://docs.astral.sh/uv/) (if you don't have it)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 3. Add the server to your MCP client

**Claude Code**

```bash
claude mcp add nsw-fuel \
  -e NSW_FUEL_API_KEY=your-key \
  -e NSW_FUEL_API_SECRET=your-secret \
  -- uvx mcp-au-nsw fuel
```

**Claude Desktop / Cursor / other clients**: add this to the MCP config file (`claude_desktop_config.json`, `.cursor/mcp.json`, etc.):

```json
{
  "mcpServers": {
    "nsw-fuel": {
      "command": "uvx",
      "args": ["mcp-au-nsw", "fuel"],
      "env": {
        "NSW_FUEL_API_KEY": "your-key",
        "NSW_FUEL_API_SECRET": "your-secret"
      }
    }
  }
}
```

## Fuel server

### Tools

| Tool | What it does | API calls |
|---|---|---|
| `find_fuel_prices` | Cheapest (or nearest) stations for a fuel type around a suburb, postcode or coordinates | 1 |
| `get_station_prices` | All current prices at one station | 1 |
| `search_stations` | Find stations by name, brand, suburb or postcode | cached |
| `list_fuel_types` | Fuel type codes (U91, E10, P98, DL, ...) | cached |

Reference data (fuel types and the ~3,300 station list) is cached for 24 hours, so station search and suburb lookups don't use your monthly quota. Prices are in cents per litre.

### Example prompts

- "Where's the cheapest diesel near UNSW?"
- "Cheapest U91 within 3 km of Redfern, sorted by distance"
- "What are the prices at BP Redfern right now?"
- "Find petrol stations in Hobart"

## Development

```bash
git clone https://github.com/fisher98kim/mcp-au-nsw
cd mcp-au-nsw
uv sync
uv run pytest

# run the server locally with keys from .env
uv run --env-file .env mcp-au-nsw fuel
```

To try local changes in Claude Code:

```bash
claude mcp add nsw-fuel-dev -e NSW_FUEL_API_KEY=... -e NSW_FUEL_API_SECRET=... \
  -- uv run --directory /path/to/mcp-au-nsw mcp-au-nsw fuel
```

## License

MIT. Not affiliated with or endorsed by the NSW Government. Data is provided by API.NSW under its own terms of use.
