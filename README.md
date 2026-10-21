# mcp-au-nsw

[MCP](https://modelcontextprotocol.io) servers for NSW Government APIs.
Ask Claude (or any MCP client) things like *"How do I get from UNSW to Circular Quay right now?"*, *"Any crashes on the M4?"* or *"Where's the cheapest diesel near Parramatta?"* and get live answers.

| Server | What it covers | Data source | Key |
|---|---|---|---|
| `transport` | Trip planning, real-time departures, service alerts (trains, metro, buses, light rail, ferries) | [TfNSW Open Data Hub](https://opendata.transport.nsw.gov.au) | TfNSW key |
| `roads` | Live traffic hazards (crashes, roadworks, floods, fires, events) and toll costs | [TfNSW Open Data Hub](https://opendata.transport.nsw.gov.au) | TfNSW key (same one) |
| `fuel` | Live fuel prices for NSW & TAS | [API.NSW](https://api.nsw.gov.au) | API.NSW key |

Each server is a separate subcommand, so you only add the ones you need.

## Quick start

### 1. Get API keys (free)

**TfNSW Open Data Hub** (for `transport` and `roads`; one key covers both)

1. Register: <https://opendata.transport.nsw.gov.au/data/user/register>
2. Log in: <https://opendata.transport.nsw.gov.au/data/user/login>
3. Click your profile icon → **API Tokens**, enter a name and click **Create API Token**.
4. Copy the token right away; it can't be viewed again. This is your `NSW_TRANSPORT_API_KEY`.

Official guide: <https://opendata.transport.nsw.gov.au/developers/userguide>

**API.NSW** (for `fuel`)

1. Register: <https://api.nsw.gov.au/Account/Register> (log in: <https://api.nsw.gov.au/Account/Login>)
2. Open the Fuel API page and click **Subscribe**, or go to **My Apps → Add new app** and attach the **Fuel API**: <https://api.nsw.gov.au/Product/Index/22>
   (Each app can have only one API product.)
3. Copy the app's **API Key** and **API Secret** into `NSW_FUEL_API_KEY` and `NSW_FUEL_API_SECRET`.
   The free plan allows 2,500 calls per month.

### 2. Install [uv](https://docs.astral.sh/uv/) (if you don't have it)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 3. Add the servers to your MCP client

**Claude Code**

```bash
claude mcp add nsw-transport -e NSW_TRANSPORT_API_KEY=your-tfnsw-key -- uvx mcp-au-nsw transport
claude mcp add nsw-roads     -e NSW_TRANSPORT_API_KEY=your-tfnsw-key -- uvx mcp-au-nsw roads
claude mcp add nsw-fuel      -e NSW_FUEL_API_KEY=your-key -e NSW_FUEL_API_SECRET=your-secret -- uvx mcp-au-nsw fuel
```

**Claude Desktop / Cursor / other clients**: add the servers you want to the MCP config file (`claude_desktop_config.json`, `.cursor/mcp.json`, etc.):

```json
{
  "mcpServers": {
    "nsw-transport": {
      "command": "uvx",
      "args": ["mcp-au-nsw", "transport"],
      "env": { "NSW_TRANSPORT_API_KEY": "your-tfnsw-key" }
    },
    "nsw-roads": {
      "command": "uvx",
      "args": ["mcp-au-nsw", "roads"],
      "env": { "NSW_TRANSPORT_API_KEY": "your-tfnsw-key" }
    },
    "nsw-fuel": {
      "command": "uvx",
      "args": ["mcp-au-nsw", "fuel"],
      "env": { "NSW_FUEL_API_KEY": "your-key", "NSW_FUEL_API_SECRET": "your-secret" }
    }
  }
}
```

`uvx` caches the version it first downloads. To pick up a new release, use `uvx mcp-au-nsw@latest ...` or run `uv cache clean mcp-au-nsw`.

## How the servers behave

- **Places by name.** Tools that take a place accept names ("Town Hall", "17 High St Kensington", "Sydney Opera House"), stop IDs, or `lat,lng`.
- **No guessing.** If a name matches several places about equally well (e.g. "UNSW" has two light rail stops, "Sydney Airport" has domestic and international stations), the tool returns the candidates instead of picking one, so the assistant can ask you.
- **Live data, no caching.** Every call fetches fresh data. Responses include stable IDs (stop IDs, station codes) so you can build your own lookups for analysis.
- **Sydney local time.** All times are `YYYY-MM-DD HH:MM` in Sydney time.

## `transport` server

| Tool | What it does |
|---|---|
| `plan_trip` | A-to-B journeys with legs, platforms, real-time delays and alerts. Supports arrive-by times and limiting modes |
| `get_departures` | Next departures from a station or stop, with real-time delays and platforms |
| `get_service_alerts` | Current disruptions and trackwork, filtered by mode, line (`T1`, `L2`, `333`, ...) or stop |
| `find_stops` | Search stations, stops and wharves by name; returns stop IDs and modes |

Example prompts:

- "How do I get from UNSW to Circular Quay right now?"
- "I need to be at Manly Wharf by 6pm. When should I leave Martin Place?"
- "When's the next train from Town Hall?"
- "Any problems on the T1 today?"

## `roads` server

| Tool | What it does |
|---|---|
| `get_traffic_hazards` | Crashes, breakdowns, roadworks, floods, fires, alpine conditions and major events. Filter by area/road name or distance from a place |
| `calculate_toll` | Toll cost (AUD) and motorways used between two places, compared with the quickest toll-free route |

Example prompts:

- "Anything happening on the M4 right now?"
- "Any roadworks or events near Parramatta this weekend?"
- "How much are the tolls from Parramatta to Sydney International Airport, and how much time do they save?"

Toll amounts are estimates from Transport for NSW and may differ from what is actually charged.

## `fuel` server

| Tool | What it does | API calls |
|---|---|---|
| `find_fuel_prices` | Cheapest (or nearest) stations for a fuel type around a suburb, postcode or coordinates | 1 (2 with a suburb/postcode) |
| `get_station_prices` | All current prices at one station | 1 |
| `search_stations` | Find stations by name, brand, suburb or postcode | 1 |
| `list_fuel_types` | Fuel type codes (U91, E10, P98, DL, ...) | 1 |

Prices are in cents per litre.

Example prompts:

- "Where's the cheapest diesel near UNSW?"
- "What are the prices at BP Redfern right now?"

## Development

```bash
git clone https://github.com/fisher98kim/mcp-au-nsw
cd mcp-au-nsw
uv sync
uv run pytest

# run a server locally with keys from .env
uv run --env-file .env mcp-au-nsw transport
```

To try local changes in Claude Code:

```bash
claude mcp add nsw-transport-dev -e NSW_TRANSPORT_API_KEY=... \
  -- uv run --directory /path/to/mcp-au-nsw mcp-au-nsw transport
```

## License

MIT. Not affiliated with or endorsed by the NSW Government or Transport for NSW. Data is provided by API.NSW and the TfNSW Open Data Hub under their own terms of use.
