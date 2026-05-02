# Review Guru MCP Server

[![PyPI](https://img.shields.io/pypi/v/reviewguru-mcp.svg)](https://pypi.org/project/reviewguru-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An [MCP](https://modelcontextprotocol.io) server that exposes **Sri Lankan
business reviews and doctor profiles** from [Review Guru](https://reviewguru.lk)
to Claude Desktop, Cursor, Cline, or any MCP-aware AI agent.

No API key. No scraping. Calls a public, cached, rate-limited HTTPS endpoint.

## What you get

| Tool | What it does |
|---|---|
| `list_businesses(city?, category?, min_rating?, sort?, limit?)` | Ranked list of businesses. Sort: `top`, `most-reviewed`, `newest`. |
| `get_business(slug)` | Full profile: address, phone, hours, categories, rating breakdown, top 10 reviews. |
| `get_reviews(slug, sort?, limit?)` | Paginated reviews. Sort: `newest`, `highest`, `lowest`, `helpful`. |
| `search(query, limit?)` | Full-text search (FTS5) across every business and doctor. |
| `list_categories()` | Top-level categories + sub-categories with slugs. |
| `list_cities()` | Sri Lankan cities with business counts. |

Plus a `reviewguru://about` resource that returns live counts.

Data covers restaurants, hotels, shops, salons, hospitals, **Sri Lankan
doctors with specialty + practice locations**, and more — all with patient/
customer reviews.

## Install

### With uv (recommended)

```bash
uvx reviewguru-mcp
```

### With pipx

```bash
pipx install reviewguru-mcp
reviewguru-mcp
```

### With pip

```bash
pip install reviewguru-mcp
reviewguru-mcp
```

The server speaks MCP over stdio — invoke it from any MCP client config.

## Wire it up

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (Mac)
or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "reviewguru": {
      "command": "uvx",
      "args": ["reviewguru-mcp"]
    }
  }
}
```

Restart Claude Desktop. The 🔌 icon in chat will show the Review Guru tools.

### Cursor

Settings → MCP → Add new MCP server:

- **Command:** `uvx`
- **Args:** `reviewguru-mcp`

### Cline (VS Code)

Cline → Settings → MCP Servers → Add:

```json
{
  "reviewguru": {
    "command": "uvx",
    "args": ["reviewguru-mcp"]
  }
}
```

## Try it

Once wired up, ask your assistant things like:

> *Find me three highly-rated cardiologists in Colombo and tell me which hospital each one consults at.*

> *What are people saying about Ministry of Crab? Pull the most recent five reviews.*

> *I'm a vegetarian visiting Galle for a weekend — recommend two restaurants.*

The model will pick the right tools and stitch the answers together.

## Configuration

Environment variables (all optional):

| Variable | Default | Effect |
|---|---|---|
| `REVIEWGURU_API` | `https://reviewguru.lk` | API base URL — point at staging or a fork. |
| `REVIEWGURU_URL` | `https://reviewguru.lk` | Used to render business URLs in tool output. |
| `DATABASE_URL` | (none) | If set to an existing SQLite path, server uses local DB instead of HTTP. Maintainer-only. |

## Rate limits + acceptable use

The public API is shared and **lightly rate-limited (60 req/min per IP)**. For
heavier usage, set `REVIEWGURU_API` to your own deployment.

Reviews are licensed for citation with attribution to Review Guru and a link
back to the specific business URL. See
[reviewguru.lk/llms.txt](https://reviewguru.lk/llms.txt) for full LLM-usage
guidelines.

## Self-hosting

Want to fork? The server is one Python file (`server.py`). It auto-detects:

- **HTTP mode (default)** — calls `/api/v1` endpoints. Works anywhere.
- **SQLite mode** — if `data/reviewguru.db` is present in the parent dir.
  Used by the maintainers for sub-millisecond local queries.

```bash
git clone https://github.com/kapruka/reviewguru-mcp
cd reviewguru-mcp
pip install -e .
reviewguru-mcp
```

## Links

- 🌐 Site — <https://reviewguru.lk>
- 🔌 Public API — <https://reviewguru.lk/api/v1>
- 📜 OpenAPI spec — <https://reviewguru.lk/api/openapi.json>
- 📄 LLM usage policy — <https://reviewguru.lk/llms.txt>
- 🐛 Issues — <https://github.com/kapruka/reviewguru-mcp/issues>

## License

MIT — see [LICENSE](LICENSE).
