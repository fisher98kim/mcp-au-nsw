"""NSW licence and public register lookups MCP server (API.NSW).

Covers 15 public registers (tradespeople, property agents, security, liquor, pharmacies, WHS licences, ...).
They all share one API shape: verify (by licence number), browse (by name) and details (by licence ID).

API.NSW allows one API product per app, so each register has its own key pair:
NSW_<REGISTER>_API_KEY / NSW_<REGISTER>_API_SECRET (e.g. NSW_TRADES_API_KEY). Only registers with keys set
can be queried; the rest report how to subscribe.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from mcp_au_nsw.core import ApiNswClient, ApiNswError

# The browse endpoint returns at most this many results.
BROWSE_CAP = 200


@dataclass(frozen=True)
class Register:
    name: str
    path: str
    product_id: int
    covers: str

    @property
    def subscribe_url(self) -> str:
        return f"https://api.nsw.gov.au/Product/Index/{self.product_id}"


REGISTERS: dict[str, Register] = {
    "trades": Register("Trades", "/tradesregister/v1", 25, "Building contractors and tradespeople (builders, electricians, plumbers, ...)"),
    "property": Register("Property", "/propertyregister/v1", 20, "Real estate agents, property managers, strata managers, stock and station agents"),
    "security": Register("Security", "/securityregister/v1", 24, "Security guards and security businesses"),
    "liquor": Register("Liquor", "/liquorregister/v1", 19, "Liquor licences, licensed premises and related parties"),
    "motor": Register("Motor", "/motor/v1", 15, "Motor dealers, repairers, recyclers and motor tradespeople"),
    "conveyancer": Register("Conveyancer", "/conveyancer/v1", 17, "Licensed conveyancers"),
    "lotteries": Register("Lotteries", "/lotteries/v1", 16, "Trade promotion lotteries and games of chance permits"),
    "owner_builder": Register("Owner Builder Permit", "/ownerbuilder/v1", 21, "Owner builder permits for residential property owners"),
    "home_building_compensation": Register("Home Building Compensation", "/hbccheckregister/v1", 36, "Home building compensation (insurance) certificates"),
    "building_practitioners": Register("Design and Building Practitioners", "/dbpregister/v1", 29, "Registered design, building and professional engineer practitioners"),
    "asbestos": Register("Asbestos and Demolition", "/asbestosregister/v1", 31, "Asbestos removal and demolition licences (WHS)"),
    "high_risk_work": Register("High Risk Work", "/hrwregister/v1", 33, "High risk work licences: forklifts, cranes, scaffolding, ... (WHS)"),
    "white_cards": Register("White Cards and Traffic Control", "/wcregister/v1", 32, "Construction induction (white) cards and traffic control work cards (WHS)"),
    "trainers": Register("Trainers and Providers", "/rto/v1", 13, "Registered training organisations for high risk work and construction induction"),
    "pharmacies": Register("Pharmacies", "/pharmacyregister/v1", 30, "Approved pharmacy premises and financial interest holders"),
}
RegisterSlug = Literal[
    "trades",
    "property",
    "security",
    "liquor",
    "motor",
    "conveyancer",
    "lotteries",
    "owner_builder",
    "home_building_compensation",
    "building_practitioners",
    "asbestos",
    "high_risk_work",
    "white_cards",
    "trainers",
    "pharmacies",
]

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

mcp = MCPServer(
    name="nsw-licences",
    instructions=(
        "Check NSW licences and public registers: tradespeople, property agents, security, liquor, motor dealers, "
        "conveyancers, pharmacies, WHS licences and more. Use verify_licence when you have a licence number, "
        "search_licences to find by person or business name, and get_licence_details for the full record "
        "(licence classes, conditions, disciplinary and compliance history). Call list_registers to see which "
        "registers are available. A current licence may not cover the work in question; check the licence classes."
    ),
)

_clients: dict[str, ApiNswClient] = {}


def _env_prefix(slug: str) -> str:
    """'owner_builder' -> 'NSW_OWNER_BUILDER' (then _API_KEY / _API_SECRET)."""
    return f"NSW_{slug.upper()}"


def _keys(slug: str) -> tuple[str, str]:
    prefix = _env_prefix(slug)
    return os.environ.get(f"{prefix}_API_KEY", ""), os.environ.get(f"{prefix}_API_SECRET", "")


def _get_client(slug: str) -> ApiNswClient:
    if slug not in _clients:
        key, secret = _keys(slug)
        if not key or not secret:
            reg = REGISTERS[slug]
            prefix = _env_prefix(slug)
            raise ToolError(
                f"The {reg.name} register is not configured: set {prefix}_API_KEY and {prefix}_API_SECRET. "
                f"Subscribe to it at {reg.subscribe_url} (one API.NSW app per register)."
            )
        _clients[slug] = ApiNswClient(key, secret)
    return _clients[slug]


async def _call(slug: str, endpoint: str, **params: Any) -> Any:
    try:
        return await _get_client(slug).request("GET", f"{REGISTERS[slug].path}/{endpoint}", params=params)
    except ApiNswError as e:
        raise ToolError(str(e)) from e


_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_EMPTY = (None, "", "N/A", [], {})


def _clean(value: Any) -> Any:
    """Normalise a register record without dropping information.

    Dates 'dd/mm/yyyy' -> 'yyyy-mm-dd'; 'True'/'False' -> booleans; empty values ('', 'N/A', null, [], {}) removed;
    exact duplicate list items removed (the API repeats associated licences).
    """
    if isinstance(value, dict):
        cleaned = {k: _clean(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v not in _EMPTY}
    if isinstance(value, list):
        items, seen = [], set()
        for item in (_clean(v) for v in value):
            key = repr(item)
            if item in _EMPTY or key in seen:
                continue
            seen.add(key)
            items.append(item)
        return items
    if isinstance(value, str):
        text = value.strip()
        if m := _DATE_RE.match(text):
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        if text in ("True", "False"):
            return text == "True"
        return text
    return value


def _business_names(value: Any) -> list[str]:
    """businessNames is a string in some registers and a list of {businessName} in others."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [b.get("businessName") for b in value if isinstance(b, dict) and b.get("businessName")]
    return []


def _summary(record: dict[str, Any], slug: str) -> dict[str, Any]:
    return {"register": slug, **_clean({**record, "businessNames": _business_names(record.get("businessNames"))})}


@mcp.tool(annotations=READ_ONLY)
async def list_registers() -> list[dict[str, Any]]:
    """List the NSW registers this server can search, what each covers, and whether its API key is configured."""
    return [
        {
            "register": slug,
            "name": reg.name,
            "covers": reg.covers,
            "configured": all(_keys(slug)),
            "subscribe_url": reg.subscribe_url,
        }
        for slug, reg in REGISTERS.items()
    ]


@mcp.tool(annotations=READ_ONLY)
async def verify_licence(register: RegisterSlug, licence_number: str) -> dict[str, Any]:
    """Check a licence number on a NSW register: status (Current/Expired/...), expiry date, licence type and holder.

    licence_number: as printed on the licence or quote, e.g. "241132C". If not found, the number may belong to a
    different register.
    """
    results = await _call(register, "verify", licenceNumber=licence_number.strip())
    licences = [_summary(r, register) for r in results or []]
    if not licences:
        return {
            "register": register,
            "licence_number": licence_number,
            "found": False,
            "message": (
                f"No licence numbered '{licence_number}' on the {REGISTERS[register].name} register. "
                "Check the number, or try another register or search_licences by name."
            ),
        }
    return {"register": register, "licence_number": licence_number, "found": True, "licences": licences}


@mcp.tool(annotations=READ_ONLY)
async def search_licences(
    register: RegisterSlug,
    query: str,
    current_only: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    """Search a NSW register by person or business name (partial names work). Current licences are listed first.

    Returns licence_id values for get_licence_details. The register returns at most 200 matches, so use a more
    specific name if `truncated` is true.
    """
    results = await _call(register, "browse", searchText=query.strip()) or []
    licences = [_summary(r, register) for r in results]
    if current_only:
        licences = [l for l in licences if str(l.get("status", "")).lower() == "current"]
    licences.sort(key=lambda l: str(l.get("status", "")).lower() != "current")
    return {
        "register": register,
        "query": query,
        "total_matched": len(licences),
        "truncated": len(results) >= BROWSE_CAP,
        "licences": licences[:limit],
    }


@mcp.tool(annotations=READ_ONLY)
async def get_licence_details(register: RegisterSlug, licence_id: str) -> dict[str, Any]:
    """Full public-register record for one licence: classes (what work it covers), conditions, history,
    premises, associated people and licences, and compliance actions (disciplinary actions, suspensions,
    prosecutions, public warnings, insurance claims).

    licence_id: the `licenceID` from verify_licence or search_licences (not the licence number).
    """
    data = await _call(register, "details", licenceid=licence_id.strip())
    if not data:
        raise ToolError(
            f"No record for licence_id '{licence_id}' on the {REGISTERS[register].name} register. "
            "Use the licenceID from verify_licence or search_licences, not the licence number."
        )
    return {"register": register, "licence_id": licence_id, **_clean(data)}


def run() -> None:
    # httpx logs every request at INFO, which clutters MCP client logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run()
