"""MCP servers for NSW Government APIs. Usage: mcp-au-nsw <server>  (e.g. mcp-au-nsw fuel)"""

import sys

SERVERS = ("fuel", "transport", "roads", "licences")


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name == "fuel":
        from mcp_au_nsw.fuel.server import run
    elif name == "transport":
        from mcp_au_nsw.transport.server import run
    elif name == "roads":
        from mcp_au_nsw.roads.server import run
    elif name == "licences":
        from mcp_au_nsw.licences.server import run
    else:
        print(f"usage: mcp-au-nsw <{'|'.join(SERVERS)}>", file=sys.stderr)
        sys.exit(2)
    run()
