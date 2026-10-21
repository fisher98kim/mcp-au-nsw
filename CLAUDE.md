# mcp-au-nsw

MCP servers for NSW Government APIs, published to PyPI as `mcp-au-nsw` (one subcommand per server: `uvx mcp-au-nsw fuel`).

## Rules

- **Correctness over convenience.** When a tool can't be sure, it says so instead of guessing.
- **Tools that take a place accept IDs and human-readable names, but never guess.** If several candidates match about equally well, return an error listing them (with IDs) so the LLM can pick or ask the user. Always include the resolved place name in the response.
- **No data caching.** Every tool call fetches fresh data from the API. Callers that need reference data repeatedly (e.g. for data analysis) save their own mapping files locally, so they control freshness. (Reusing an auth token until it expires is not data caching.)
- **Always return stable IDs/codes** (station codes, stop IDs, fuel type codes) alongside names, so callers can build their own mappings and chain tool calls.
- **Trim API responses, but when in doubt keep the field.** Don't pass raw responses through (they can be tens of KB), but keep anything a user could reasonably ask about.
- **No Korean anywhere in the repository.** Code, comments, docstrings, tool descriptions, error messages, tests, workflows and docs are all written in English.
- **Times are Sydney local time, formatted `YYYY-MM-DD HH:MM`.** Convert UTC timestamps from APIs before returning them.
- **Tools that return lists take a `limit` parameter.**
- **Error messages tell the user/LLM what to do next** (e.g. where to get a key, which tool to try instead).
- **Commit, push and release only after the user confirms.**
