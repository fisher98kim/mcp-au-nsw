"""API.NSW 용 MCP 서버 모음. 사용법: mcp-au-nsw <server>  (예: mcp-au-nsw fuel)"""

import sys

SERVERS = ("fuel",)


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name == "fuel":
        from mcp_au_nsw.fuel.server import run
    else:
        print(f"usage: mcp-au-nsw <{'|'.join(SERVERS)}>", file=sys.stderr)
        sys.exit(2)
    run()
