"""Review Guru MCP server.

Exposes Sri Lankan business reviews as an MCP (Model Context Protocol) server
so Claude Desktop / Cursor / any MCP-aware AI agent can query the data
directly — no scraping, no API keys.

Two backends, auto-selected:

  * **HTTP mode (default for the published package).** Calls the public
    ``/api/v1`` endpoints over HTTPS. Anyone can run this — no database file,
    no auth. Set ``REVIEWGURU_API`` to point at a different deployment.
  * **SQLite mode (used when the local DB exists).** Reads
    ``../data/reviewguru.db`` directly. Used for local development by the
    Review Guru maintainers — zero round-trip latency.

The selection rule is simple: SQLite mode wins iff the DB file exists and
``REVIEWGURU_API`` is not set. Outside users will always get HTTP mode because
they don't have the DB.

Run from the published package:

    pipx install reviewguru-mcp     # or: uvx reviewguru-mcp
    reviewguru-mcp                  # speaks MCP over stdio

Wire to Claude Desktop (``~/Library/Application Support/Claude/claude_desktop_config.json``
on Mac, ``%APPDATA%\\Claude\\claude_desktop_config.json`` on Windows):

    {
      "mcpServers": {
        "reviewguru": {
          "command": "uvx",
          "args": ["reviewguru-mcp"]
        }
      }
    }
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "reviewguru.db"
DB_PATH = Path(os.environ.get("DATABASE_URL", str(DEFAULT_DB)))

# Default to the live Review Guru deployment. Override for staging or a
# self-hosted fork.
API_BASE = os.environ.get("REVIEWGURU_API", "https://reviewguru.lk").rstrip("/")
SITE_URL = os.environ.get("REVIEWGURU_URL", "https://reviewguru.lk").rstrip("/")

# Mode selection: SQLite only if the DB file is present AND no explicit API
# override. Anything else falls back to HTTP, which always works.
USE_SQLITE = (
    DB_PATH.exists() and "REVIEWGURU_API" not in os.environ
)

mcp = FastMCP("reviewguru")

_HTTP_CLIENT: Optional[httpx.Client] = None


def _client() -> httpx.Client:
    """Lazy singleton — keep one connection pool for the whole server."""
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        _HTTP_CLIENT = httpx.Client(
            base_url=f"{API_BASE}/api/v1",
            timeout=httpx.Timeout(15.0, connect=8.0),
            headers={"User-Agent": "reviewguru-mcp/1.0"},
        )
    return _HTTP_CLIENT


def _fix_url(url: Any) -> str:
    """Prod returns biz URLs with the wrong host occasionally (env mismatch).
    Rewrite to whatever SITE_URL says."""
    if not isinstance(url, str):
        return ""
    return re.sub(r"^https?://[^/]+", SITE_URL, url)


def _api_get(path: str, **params: Any) -> Any:
    """Call /api/v1/<path>, unwrap {data: ...}, raise on HTTP errors."""
    clean = {k: v for k, v in params.items() if v is not None}
    r = _client().get(path, params=clean)
    r.raise_for_status()
    payload = r.json()
    return payload.get("data", payload)


# ------------------------------------------------------------------------
# SQLite backend (local-dev fast path)
# ------------------------------------------------------------------------

if USE_SQLITE:
    import sqlite3

    def _conn() -> sqlite3.Connection:
        c = sqlite3.connect(str(DB_PATH))
        c.row_factory = sqlite3.Row
        return c

    def _biz_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "slug": row["slug"],
            "name": row["name"],
            "url": f"{SITE_URL}/biz/{row['slug']}",
            "averageRating": float(row["avg_rating"] or 0),
            "reviewCount": int(row["review_count"] or 0),
            "address": (row["address"] or "").strip() or None,
            "priceLevel": row["price_level"],
        }


# ------------------------------------------------------------------------
# Tools — same signature regardless of backend
# ------------------------------------------------------------------------


@mcp.tool()
def list_businesses(
    city: Optional[str] = None,
    category: Optional[str] = None,
    min_rating: Optional[float] = None,
    sort: str = "top",
    limit: int = 25,
) -> list[dict[str, Any]]:
    """List Sri Lankan businesses with optional filters.

    Args:
        city: City slug (e.g. "colombo", "nugegoda", "dehiwala"). Use list_cities() to discover.
        category: Category slug (e.g. "restaurants", "shopping", "doctors"). Use list_categories() to discover.
        min_rating: Minimum average rating 1-5.
        sort: "top" (Bayesian-weighted best), "most-reviewed", or "newest".
        limit: Max results, 1-100 (default 25).
    """
    limit = max(1, min(100, int(limit)))

    if USE_SQLITE:
        filters = ["b.status = 'active'"]
        args: list[Any] = []
        if city:
            filters.append(
                "EXISTS (SELECT 1 FROM locations loc WHERE loc.id = b.location_id "
                "AND (loc.slug = ? OR loc.parent_id = (SELECT id FROM locations WHERE slug = ?)))"
            )
            args.extend([city, city])
        if category:
            filters.append(
                "EXISTS (SELECT 1 FROM business_categories bc "
                "JOIN categories c ON c.id = bc.category_id "
                "WHERE bc.business_id = b.id AND "
                "(c.slug = ? OR c.parent_id = (SELECT id FROM categories WHERE slug = ?)))"
            )
            args.extend([category, category])
        if min_rating is not None:
            filters.append("b.avg_rating >= ?")
            args.append(float(min_rating))

        if sort == "newest":
            order = "b.created_at DESC"
        elif sort == "most-reviewed":
            order = "b.review_count DESC, b.avg_rating DESC"
        else:
            order = (
                "(CASE WHEN b.review_count = 0 THEN 0 "
                "ELSE (3.8 * 5 + b.avg_rating * b.review_count) / (5 + b.review_count) END) DESC, "
                "b.review_count DESC"
            )

        sql = f"""
            SELECT b.slug, b.name, b.avg_rating, b.review_count, b.address, b.price_level
            FROM businesses b
            WHERE {" AND ".join(filters)}
            ORDER BY {order}
            LIMIT {limit}
        """
        with _conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [_biz_to_dict(r) for r in rows]

    # HTTP mode
    raw = _api_get(
        "/businesses",
        city=city,
        category=category,
        minRating=min_rating,
        sort=sort,
        limit=limit,
    )
    if not isinstance(raw, list):
        return []
    out = []
    for b in raw:
        out.append(
            {
                "slug": b.get("slug"),
                "name": b.get("name"),
                "url": _fix_url(b.get("url")),
                "averageRating": float(b.get("averageRating") or 0),
                "reviewCount": int(b.get("reviewCount") or 0),
                "address": (b.get("address") or "").strip() or None,
                "priceLevel": b.get("priceLevel"),
                "primaryCategory": b.get("primaryCategory"),
                "city": b.get("location"),
            }
        )
    return out


@mcp.tool()
def get_business(slug: str) -> dict[str, Any]:
    """Get full details of a single business by slug, including location,
    contact info, categories, and the top 10 recent reviews.
    """
    if USE_SQLITE:
        with _conn() as c:
            row = c.execute(
                "SELECT * FROM businesses WHERE slug = ? AND status = 'active'", (slug,)
            ).fetchone()
            if not row:
                raise ValueError(f"Business not found: {slug}")
            categories = [
                r["name"]
                for r in c.execute(
                    "SELECT c.name FROM business_categories bc "
                    "JOIN categories c ON c.id = bc.category_id "
                    "WHERE bc.business_id = ? ORDER BY bc.is_primary DESC",
                    (row["id"],),
                ).fetchall()
            ]
            reviews = [
                {
                    "rating": r["rating"],
                    "title": r["title"],
                    "body": r["body"],
                    "author": r["reviewer_display_name"] or "Anonymous",
                    "publishedAt": r["published_at"],
                    "source": r["source"],
                }
                for r in c.execute(
                    "SELECT * FROM reviews WHERE business_id = ? AND status = 'published' "
                    "ORDER BY COALESCE(published_at, created_at) DESC LIMIT 10",
                    (row["id"],),
                ).fetchall()
            ]
        return {
            "slug": row["slug"],
            "name": row["name"],
            "url": f"{SITE_URL}/biz/{row['slug']}",
            "description": row["description"],
            "address": (row["address"] or "").strip() or None,
            "phone": row["phone"],
            "website": row["website"],
            "priceLevel": row["price_level"],
            "averageRating": float(row["avg_rating"] or 0),
            "reviewCount": row["review_count"],
            "categories": categories,
            "coordinates": (
                {"lat": row["lat"], "lng": row["lng"]}
                if row["lat"] is not None and row["lng"] is not None
                else None
            ),
            "claimed": row["claimed_by_user_id"] is not None,
            "reviews": reviews,
        }

    # HTTP mode
    try:
        b = _api_get(f"/businesses/{slug}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise ValueError(f"Business not found: {slug}") from None
        raise
    if not isinstance(b, dict):
        raise ValueError(f"Business not found: {slug}")
    revs = _api_get(f"/businesses/{slug}/reviews", sort="newest", limit=10)
    if not isinstance(revs, list):
        revs = []
    return {
        "slug": b.get("slug"),
        "name": b.get("name"),
        "url": _fix_url(b.get("url")),
        "description": b.get("description"),
        "address": (b.get("address") or "").strip() or None,
        "phone": b.get("phone"),
        "email": b.get("email"),
        "website": b.get("website"),
        "priceLevel": b.get("priceLevel"),
        "averageRating": float(b.get("averageRating") or 0),
        "reviewCount": b.get("reviewCount"),
        "ratingBreakdown": b.get("ratingBreakdown"),
        "categories": b.get("categories") or [],
        "coordinates": b.get("coordinates"),
        "city": (b.get("location") or {}).get("city"),
        "reviews": [
            {
                "rating": r.get("rating"),
                "title": r.get("title"),
                "body": r.get("body"),
                "author": r.get("author") or "Anonymous",
                "publishedAt": r.get("publishedAt"),
                "source": r.get("source"),
            }
            for r in revs
        ],
    }


@mcp.tool()
def get_reviews(slug: str, sort: str = "newest", limit: int = 20) -> list[dict[str, Any]]:
    """Get reviews for a business.

    Args:
        slug: Business slug.
        sort: "newest", "highest", "lowest", or "helpful".
        limit: Max reviews, 1-100 (default 20).
    """
    limit = max(1, min(100, int(limit)))

    if USE_SQLITE:
        order = {
            "newest": "created_at DESC",
            "highest": "rating DESC, created_at DESC",
            "lowest": "rating ASC, created_at DESC",
            "helpful": "helpful_count DESC, created_at DESC",
        }.get(sort, "created_at DESC")
        with _conn() as c:
            biz = c.execute(
                "SELECT id, name FROM businesses WHERE slug = ? AND status = 'active'", (slug,)
            ).fetchone()
            if not biz:
                raise ValueError(f"Business not found: {slug}")
            rows = c.execute(
                f"SELECT * FROM reviews WHERE business_id = ? AND status = 'published' "
                f"ORDER BY {order} LIMIT {limit}",
                (biz["id"],),
            ).fetchall()
        return [
            {
                "rating": r["rating"],
                "title": r["title"],
                "body": r["body"],
                "author": r["reviewer_display_name"] or "Anonymous",
                "publishedAt": r["published_at"],
                "source": r["source"],
            }
            for r in rows
        ]

    # HTTP mode
    try:
        revs = _api_get(f"/businesses/{slug}/reviews", sort=sort, limit=limit)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise ValueError(f"Business not found: {slug}") from None
        raise
    if not isinstance(revs, list):
        return []
    return [
        {
            "rating": r.get("rating"),
            "title": r.get("title"),
            "body": r.get("body"),
            "author": r.get("author") or "Anonymous",
            "publishedAt": r.get("publishedAt"),
            "source": r.get("source"),
            "sourceAttribution": r.get("sourceAttribution"),
            "helpfulCount": r.get("helpfulCount"),
        }
        for r in revs
    ]


@mcp.tool()
def search(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Full-text search across all businesses. Uses SQLite FTS5 server-side.

    Args:
        query: Free text — name, cuisine, neighborhood, doctor specialty, etc.
        limit: Max results, 1-50 (default 20).
    """
    limit = max(1, min(50, int(limit)))

    if USE_SQLITE:
        tokens = [
            f'"{t}"' for t in re.sub(r"[^\w\s'-]", " ", query).split() if t
        ]
        if not tokens:
            return []
        fts_query = " OR ".join(tokens)
        with _conn() as c:
            rows = c.execute(
                """
                SELECT b.slug, b.name, b.avg_rating, b.review_count, b.address, b.price_level,
                       snippet(businesses_fts, 1, '', '', '…', 16) AS snippet
                FROM businesses_fts f
                JOIN businesses b ON b.id = f.rowid
                WHERE businesses_fts MATCH ? AND b.status = 'active'
                ORDER BY bm25(businesses_fts), b.review_count DESC
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        return [
            {**_biz_to_dict(r), "snippet": r["snippet"] or ""} for r in rows
        ]

    # HTTP mode
    raw = _api_get("/search", q=query, limit=limit)
    if not isinstance(raw, list):
        return []
    return [
        {
            "slug": r.get("slug"),
            "name": r.get("name"),
            "url": _fix_url(r.get("url")),
            "averageRating": float(r.get("averageRating") or 0),
            "reviewCount": int(r.get("reviewCount") or 0),
            "address": (r.get("address") or "").strip() or None,
            "primaryCategory": r.get("primaryCategory"),
            "snippet": r.get("snippet") or "",
        }
        for r in raw
    ]


@mcp.tool()
def list_categories() -> list[dict[str, Any]]:
    """List all categories with their parent/child hierarchy."""
    if USE_SQLITE:
        with _conn() as c:
            rows = c.execute(
                "SELECT id, slug, name, parent_id FROM categories WHERE active = 1 "
                "ORDER BY display_order, name"
            ).fetchall()
        tops = [r for r in rows if r["parent_id"] is None]
        return [
            {
                "slug": t["slug"],
                "name": t["name"],
                "subcategories": [
                    {"slug": r["slug"], "name": r["name"]}
                    for r in rows
                    if r["parent_id"] == t["id"]
                ],
            }
            for t in tops
        ]

    raw = _api_get("/categories")
    if not isinstance(raw, list):
        return []
    return raw


@mcp.tool()
def list_cities() -> list[dict[str, Any]]:
    """List all cities on the platform with counts of listed businesses."""
    if USE_SQLITE:
        with _conn() as c:
            rows = c.execute(
                """
                SELECT loc.slug, loc.name,
                       (SELECT COUNT(*) FROM businesses b
                        WHERE b.status = 'active'
                          AND (b.location_id = loc.id
                               OR b.location_id IN (SELECT id FROM locations WHERE parent_id = loc.id))
                       ) AS biz_count
                FROM locations loc
                WHERE loc.type = 'city'
                ORDER BY biz_count DESC, loc.name
                """
            ).fetchall()
        return [
            {"slug": r["slug"], "name": r["name"], "businessCount": r["biz_count"]}
            for r in rows
        ]

    raw = _api_get("/cities")
    if not isinstance(raw, list):
        return []
    return [
        {
            "slug": c.get("slug"),
            "name": c.get("name"),
            "businessCount": c.get("businessCount"),
        }
        for c in raw
    ]


@mcp.resource("reviewguru://about")
def about() -> str:
    """Human-readable description of the Review Guru MCP server."""
    backend = "SQLite (local)" if USE_SQLITE else f"HTTP ({API_BASE}/api/v1)"
    if USE_SQLITE:
        with _conn() as c:
            biz = c.execute(
                "SELECT COUNT(*) n FROM businesses WHERE status = 'active'"
            ).fetchone()["n"]
            rev = c.execute(
                "SELECT COUNT(*) n FROM reviews WHERE status = 'published'"
            ).fetchone()["n"]
        counts = f"{biz} active businesses, {rev} published reviews"
    else:
        try:
            r = _client().get("/businesses", params={"limit": 1}).json()
            counts = f"~{r.get('total', 'thousands of')} active businesses"
        except Exception:
            counts = "thousands of active businesses"

    return (
        f"Review Guru MCP — read-only access to Sri Lankan businesses, "
        f"doctors, and reviews. Backend: {backend}. {counts}. "
        f"Tools: list_businesses, get_business, get_reviews, search, "
        f"list_categories, list_cities. Public site: {SITE_URL}."
    )


def main() -> None:
    """Entry point used by the ``reviewguru-mcp`` console script."""
    if USE_SQLITE and not DB_PATH.exists():
        # Defensive — USE_SQLITE already gates on this, but keep a clear error.
        raise SystemExit(
            f"Review Guru DB not found at {DB_PATH}. "
            "Set REVIEWGURU_API to use HTTP mode instead."
        )
    mcp.run()


if __name__ == "__main__":
    main()
