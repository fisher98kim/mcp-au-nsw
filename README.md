# mcp-au-nsw

[MCP](https://modelcontextprotocol.io) servers for NSW Government APIs.
Ask Claude (or any MCP client) things like *"How do I get from UNSW to Circular Quay right now?"*, *"Any crashes on the M4?"*, *"Is electrician licence 241132C current?"* or *"Where's the cheapest diesel near Parramatta?"* and get live answers.

| Server | What it covers | Data source | Key |
|---|---|---|---|
| `transport` | Trip planning, real-time departures, service alerts (trains, metro, buses, light rail, ferries), Park&Ride car parks | [TfNSW Open Data Hub](https://opendata.transport.nsw.gov.au) | TfNSW key |
| `roads` | Live traffic hazards (crashes, roadworks, floods, fires, events) and toll costs | [TfNSW Open Data Hub](https://opendata.transport.nsw.gov.au) | TfNSW key (same one) |
| `licences` | Licence checks on 15 NSW public registers (tradespeople, property agents, security, liquor, pharmacies, WHS licences, ...) | [API.NSW](https://api.nsw.gov.au) | One API.NSW key per register |
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

**API.NSW** (for `fuel` and `licences`)

1. Register: <https://api.nsw.gov.au/Account/Register> (log in: <https://api.nsw.gov.au/Account/Login>)
2. Go to **My Apps → Add new app**: <https://api.nsw.gov.au/DeveloperApp/AppCreate>
   and attach one API product. **Each app can have only one API product**, so create one app per API you want
   (e.g. one for the Fuel API, one for the Trades register).
3. Copy each app's **API Key** and **API Secret** into the matching environment variables
   (`NSW_FUEL_API_KEY` / `NSW_FUEL_API_SECRET`, `NSW_TRADES_API_KEY` / `NSW_TRADES_API_SECRET`, ...;
   see the [`licences` section](#licences-server) for the full list).
   The free plan allows 2,500 calls per month per app.

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
claude mcp add nsw-licences  -e NSW_TRADES_API_KEY=your-key -e NSW_TRADES_API_SECRET=your-secret -- uvx mcp-au-nsw licences
```

For `licences`, pass the key pair of every register you subscribed to; registers without keys are simply unavailable.

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
    },
    "nsw-licences": {
      "command": "uvx",
      "args": ["mcp-au-nsw", "licences"],
      "env": {
        "NSW_TRADES_API_KEY": "your-key", "NSW_TRADES_API_SECRET": "your-secret",
        "NSW_PROPERTY_API_KEY": "your-key", "NSW_PROPERTY_API_SECRET": "your-secret"
      }
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
| `get_car_park_availability` | Live free spaces at Transport Park&Ride car parks, by name or distance from a place |
| `get_car_park_history` | How full a Park&Ride car park was through a given day: hourly occupancy, peak, and when it filled up |

Example prompts:

- "How do I get from UNSW to Circular Quay right now?"
- "I need to be at Manly Wharf by 6pm. When should I leave Martin Place?"
- "When's the next train from Town Hall?"
- "Any problems on the T1 today?"
- "Are there any spaces left at the Tallawong Park&Ride?"
- "What time did the Tallawong P1 car park fill up yesterday?"

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

## `licences` server

Checks licences on NSW public registers. All registers work the same way: look up a licence number, search by
person or business name, and get the full public record.

| Tool | What it does |
|---|---|
| `verify_licence` | Check a licence number: status (Current/Expired/...), expiry, licence type and holder |
| `search_licences` | Find licences by person or business name (partial names work), current ones first |
| `get_licence_details` | Full record: licence classes (what work it covers), conditions, history, premises, associated people and licences, and compliance actions (disciplinary actions, suspensions, prosecutions, public warnings, insurance claims) |
| `list_registers` | Which registers exist, what they cover, and which are configured |

| Register (`register` value) | Covers | Environment variables | Subscribe |
|---|---|---|---|
| `trades` | Building contractors and tradespeople | `NSW_TRADES_API_KEY`, `NSW_TRADES_API_SECRET` | [Trades API](https://api.nsw.gov.au/Product/Index/25) |
| `property` | Real estate agents, property and strata managers | `NSW_PROPERTY_API_*` | [Property API](https://api.nsw.gov.au/Product/Index/20) |
| `security` | Security guards and businesses | `NSW_SECURITY_API_*` | [Security API](https://api.nsw.gov.au/Product/Index/24) |
| `liquor` | Liquor licences and premises | `NSW_LIQUOR_API_*` | [Liquor API](https://api.nsw.gov.au/Product/Index/19) |
| `motor` | Motor dealers, repairers, recyclers | `NSW_MOTOR_API_*` | [Motor API](https://api.nsw.gov.au/Product/Index/15) |
| `conveyancer` | Conveyancers | `NSW_CONVEYANCER_API_*` | [Conveyancer API](https://api.nsw.gov.au/Product/Index/17) |
| `lotteries` | Trade promotion lotteries and games of chance | `NSW_LOTTERIES_API_*` | [Lotteries API](https://api.nsw.gov.au/Product/Index/16) |
| `owner_builder` | Owner builder permits | `NSW_OWNER_BUILDER_API_*` | [Owner Builder Permit API](https://api.nsw.gov.au/Product/Index/21) |
| `home_building_compensation` | Home building compensation certificates | `NSW_HOME_BUILDING_COMPENSATION_API_*` | [Home Building Compensation API](https://api.nsw.gov.au/Product/Index/36) |
| `building_practitioners` | Design and building practitioners, engineers | `NSW_BUILDING_PRACTITIONERS_API_*` | [Design and Building Practitioners API](https://api.nsw.gov.au/Product/Index/29) |
| `asbestos` | Asbestos removal and demolition licences | `NSW_ASBESTOS_API_*` | [Asbestos and Demolition](https://api.nsw.gov.au/Product/Index/31) |
| `high_risk_work` | High risk work licences (forklifts, cranes, ...) | `NSW_HIGH_RISK_WORK_API_*` | [High Risk Work](https://api.nsw.gov.au/Product/Index/33) |
| `white_cards` | Construction induction and traffic control cards | `NSW_WHITE_CARDS_API_*` | [White Cards](https://api.nsw.gov.au/Product/Index/32) |
| `trainers` | Registered training organisations | `NSW_TRAINERS_API_*` | [Trainers and Providers API](https://api.nsw.gov.au/Product/Index/13) |
| `pharmacies` | Pharmacy premises and financial interest holders | `NSW_PHARMACIES_API_*` | [Register of Pharmacies](https://api.nsw.gov.au/Product/Index/30) |

`NSW_X_API_*` means `NSW_X_API_KEY` and `NSW_X_API_SECRET`.

Example prompts:

- "Is electrician licence 241132C current, and does it cover electrical work?"
- "Check whether my builder, Smith Constructions, holds a current licence and has any disciplinary actions."
- "Is this real estate agent licensed?"

Records come straight from the public registers and can include the names, roles and addresses of licence holders
and associated people.

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
