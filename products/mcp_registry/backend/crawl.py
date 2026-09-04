"""Crawler for the official MCP registry (registry.modelcontextprotocol.io).

The registry exposes a paginated list API; `version=latest` collapses each server to
its newest published version. We keep active entries only and upsert on the registry's
reverse-DNS name, refreshing content fields while never touching operational state
(probe results, measured flags, links), because the crawl owns metadata, nothing else.
"""

from typing import Any

from django.utils import timezone

import requests
import structlog

from posthog.dataclasses import frozen

from products.mcp_registry.backend.constants import OFFICIAL_REGISTRY_BASE_URL, OFFICIAL_REGISTRY_MAX_PAGES
from products.mcp_registry.backend.models import MCPRegistryServer

logger = structlog.get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 30
PAGE_LIMIT = 100
# Column widths for publisher-supplied values. The registry accepts whatever a publisher
# writes, so one over-wide value would otherwise fail the whole batch on a DataError and
# stall the daily crawl for every server.
_MAX_NAME_CHARS = 400
_MAX_URL_CHARS = 2048


@frozen
class CrawlOutcome:
    created: int
    updated: int


def fetch_registry_entries() -> list[dict[str, Any]]:
    """Page through the official registry and return raw active `server` payloads."""
    entries: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(OFFICIAL_REGISTRY_MAX_PAGES):
        params: dict[str, str] = {"limit": str(PAGE_LIMIT), "version": "latest"}
        if cursor:
            params["cursor"] = cursor
        response = requests.get(OFFICIAL_REGISTRY_BASE_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        body = response.json()
        for wrapper in body.get("servers", []):
            meta = (wrapper.get("_meta") or {}).get("io.modelcontextprotocol.registry/official") or {}
            if meta.get("status", "active") != "active":
                continue
            server = wrapper.get("server") or {}
            server["_registry_meta"] = meta
            entries.append(server)
        cursor = (body.get("metadata") or {}).get("nextCursor")
        if not cursor:
            return entries
    raise RuntimeError(f"registry pagination did not terminate within {OFFICIAL_REGISTRY_MAX_PAGES} pages")


def _url_within_limit(url: str) -> str:
    """Drop an over-long URL rather than truncate it.

    A shortened URL is a different URL, and storing one would send an agent somewhere the
    publisher never listed. Dropping it only makes the server look package-only.
    """
    return url if len(url) <= _MAX_URL_CHARS else ""


def _canonical_remote_url(remotes: list[dict[str, Any]]) -> str:
    for remote in remotes:
        if remote.get("type") == "streamable-http" and remote.get("url"):
            return str(remote["url"])
    for remote in remotes:
        if remote.get("url"):
            return str(remote["url"])
    return ""


def normalize_entry(server: dict[str, Any]) -> dict[str, Any] | None:
    """Map a raw registry payload onto MCPRegistryServer content fields."""
    name = server.get("name")
    if not name or len(name) > _MAX_NAME_CHARS:
        # registry_name is the upsert key, so a truncated one could collide with a
        # different server. Skipping the entry is the safe outcome.
        return None
    remotes = [{"type": r.get("type"), "url": r.get("url")} for r in (server.get("remotes") or []) if r.get("url")]
    packages = [
        {
            "registry_type": p.get("registryType") or p.get("registry_type"),
            "identifier": p.get("identifier"),
            # Kept so a connect command can pin it. Without a version, npx resolves
            # whatever is latest when the agent runs it, which the publisher can change
            # after listing something benign.
            "version": str(p.get("version") or p.get("packageVersion") or ""),
        }
        for p in (server.get("packages") or [])
        if p.get("identifier")
    ]
    meta = server.get("_registry_meta") or {}
    return {
        "registry_name": name,
        "display_name": (server.get("title") or name.rsplit("/", 1)[-1])[:_MAX_NAME_CHARS],
        "description": server.get("description") or "",
        "canonical_url": _url_within_limit(_canonical_remote_url(remotes)),
        "remotes": remotes,
        "packages": packages,
        "repository_url": _url_within_limit((server.get("repository") or {}).get("url") or ""),
        "website_url": _url_within_limit(server.get("websiteUrl") or ""),
        "registry_meta": {
            "version": server.get("version"),
            "published_at": meta.get("publishedAt"),
            "updated_at": meta.get("updatedAt"),
        },
    }


def upsert_registry_entries(entries: list[dict[str, Any]]) -> CrawlOutcome:
    """Create/update server rows from raw registry payloads.

    Rows keep the newest payload per registry name. Servers that disappear from the
    registry are kept (their liveness signal degrades on its own via the probe).
    """
    normalized: dict[str, dict[str, Any]] = {}
    for raw in entries:
        fields = normalize_entry(raw)
        if fields is None:
            continue
        existing = normalized.get(fields["registry_name"])
        if existing is None or (fields["registry_meta"].get("published_at") or "") > (
            existing["registry_meta"].get("published_at") or ""
        ):
            normalized[fields["registry_name"]] = fields

    created = 0
    updated = 0
    known = {
        server.registry_name: server
        for server in MCPRegistryServer.objects.filter(registry_name__in=list(normalized.keys()))
    }
    for registry_name, fields in normalized.items():
        server = known.get(registry_name)
        if server is None:
            liveness = "unprobed" if fields["canonical_url"] else "package_only"
            MCPRegistryServer.objects.create(listed_in_registry=True, liveness=liveness, **fields)
            created += 1
            continue
        for attr, value in fields.items():
            setattr(server, attr, value)
        server.listed_in_registry = True
        if not fields["canonical_url"] and server.liveness == "unprobed":
            server.liveness = "package_only"
        server.save()
        updated += 1

    logger.info(
        "mcp_registry.crawl.upserted",
        created=created,
        updated=updated,
        fetched=len(entries),
        at=timezone.now().isoformat(),
    )
    return CrawlOutcome(created=created, updated=updated)


def crawl_official_registry() -> CrawlOutcome:
    return upsert_registry_entries(fetch_registry_entries())
