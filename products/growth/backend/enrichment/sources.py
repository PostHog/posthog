"""Web sources an enrichment config declares, resolved per org through Firecrawl.

Only unreachable fetch outcomes are cached; successes and every search are always re-run."""

import datetime as dt
from collections.abc import Iterable
from typing import Any, Literal

from django.utils import timezone

import structlog
from requests import RequestException

from posthog.egress.firecrawl import (
    FirecrawlEgressBudgetExhausted,
    FirecrawlNotConfigured,
    FirecrawlScrapeFailed,
    FirecrawlSearchFailed,
    scrape,
    search,
)
from posthog.egress.limiter.policies import Priority
from posthog.exceptions_capture import capture_exception

from products.growth.backend.enrichment.labels import MAX_INPUT_VALUE_CHARS, SourceSpec, render_template
from products.growth.backend.enrichment.writer import merge_into_record
from products.growth.backend.models import OrganizationEnrichment

logger = structlog.get_logger(__name__)

EGRESS_SOURCE = "growth_ai_enrichment"

CACHE_TTL = dt.timedelta(days=30)

SourceError = Literal["not_configured", "unreachable", "busy", "no_results", "unresolved"]

# Retryable next run, so a caller computing a permanent verdict must defer the org instead of
# treating a missing source as data.
TRANSIENT_SOURCE_ERRORS = frozenset({"not_configured", "busy"})


def _fetch_error(error: SourceError, url: str | None) -> dict[str, Any]:
    return {
        "kind": "fetch",
        "url": url,
        "fetched_at": timezone.now().isoformat(),
        "source": "scrape",
        "error": error,
    }


def _search_error(error: SourceError, query: str | None) -> dict[str, Any]:
    return {
        "kind": "search",
        "query": query,
        "fetched_at": timezone.now().isoformat(),
        "source": "search",
        "error": error,
    }


def _cached_unreachable_fetch(organization_id: Any, key: str, url: str) -> dict[str, Any] | None:
    record = OrganizationEnrichment.objects.filter(organization_id=organization_id).only("data").first()
    if record is None:
        return None
    sources = record.data.get("sources")
    if not isinstance(sources, dict):
        return None
    stored = sources.get(key)
    if not isinstance(stored, dict) or not stored.get("fetched_at"):
        return None
    # A changed url (new render, or a domain change) must invalidate the cache rather than serve a
    # stale scrape of a different address.
    if stored.get("error") != "unreachable" or stored.get("url") != url:
        return None
    try:
        fetched_at = dt.datetime.fromisoformat(stored["fetched_at"])
        if timezone.now() - fetched_at > CACHE_TTL:
            return None
    except (ValueError, TypeError):
        # An unparsable or naive timestamp is indistinguishable from a stale record, so treat it as a miss.
        return None
    return stored


def _cache_fetch(organization_id: Any, key: str, record: dict[str, Any]) -> None:
    try:
        merge_into_record(
            str(organization_id),
            lambda data: {"sources": {**data.get("sources", {}), key: record}},
        )
    except Exception as e:
        # A cache-write failure must not undo an already-billed scrape or fail the label.
        capture_exception(e, {"organization_id": str(organization_id), "path": "sources.fetch_source", "key": key})


def _fetch(organization_id: Any, spec: SourceSpec, url: str) -> dict[str, Any]:
    cached = _cached_unreachable_fetch(organization_id, spec.key, url)
    if cached is not None:
        return {**cached, "source": "cache"}

    try:
        scraped = scrape(url, source=EGRESS_SOURCE, formats=("markdown",), priority=Priority.BATCH)
    except FirecrawlNotConfigured:
        logger.warning("enrichment_source_fetch_degraded", error="not_configured", key=spec.key, kind=spec.kind)
        return _fetch_error("not_configured", url)
    except FirecrawlEgressBudgetExhausted:
        # Not cached, since the shared budget can refill before CACHE_TTL elapses.
        logger.warning("enrichment_source_fetch_degraded", error="busy", key=spec.key, kind=spec.kind)
        return _fetch_error("busy", url)
    except (FirecrawlScrapeFailed, RequestException):
        # A gateway error, rate limit, or timeout looks identical to an outage here, so it must not
        # be cached as unreachable.
        logger.warning("enrichment_source_fetch_degraded", error="busy", key=spec.key, kind=spec.kind)
        return _fetch_error("busy", url)

    status = scraped.status_code
    bad_status = status is not None and status != 304 and not (200 <= status < 300)
    if bad_status or not scraped.markdown:
        # Cached: a 404/403 or an empty page is a fact about the url, not a transient condition.
        record = _fetch_error("unreachable", url)
        _cache_fetch(organization_id, spec.key, record)
        return record

    stored = {
        "kind": "fetch",
        "url": url,
        "fetched_at": timezone.now().isoformat(),
        "source": "scrape",
    }
    # Provenance only, never a short-circuit: _cached_unreachable_fetch never returns a success
    # record, so a fresh page is always re-scraped for its text.
    _cache_fetch(organization_id, spec.key, stored)
    return {**stored, "markdown": scraped.markdown[:MAX_INPUT_VALUE_CHARS]}


def _search(spec: SourceSpec, query: str) -> dict[str, Any]:
    try:
        found = search(query, source=EGRESS_SOURCE, limit=spec.limit, priority=Priority.BATCH)
    except FirecrawlNotConfigured:
        logger.warning("enrichment_source_fetch_degraded", error="not_configured", key=spec.key, kind=spec.kind)
        return _search_error("not_configured", query)
    except FirecrawlEgressBudgetExhausted:
        logger.warning("enrichment_source_fetch_degraded", error="busy", key=spec.key, kind=spec.kind)
        return _search_error("busy", query)
    except (FirecrawlSearchFailed, RequestException):
        logger.warning("enrichment_source_fetch_degraded", error="busy", key=spec.key, kind=spec.kind)
        return _search_error("busy", query)

    if not found.results:
        return _search_error("no_results", query)

    return {
        "kind": "search",
        "query": query,
        "fetched_at": timezone.now().isoformat(),
        "source": "search",
        "results": [
            {"url": result.url, "title": result.title, "description": result.description} for result in found.results
        ],
    }


def fetch_source(organization_id: Any, spec: SourceSpec, *, domain: str | None, name: str | None) -> dict[str, Any]:
    """Resolves one declared source for one org. Never raises: a Firecrawl failure degrades to an
    "error" record instead of failing the label."""
    rendered = render_template(spec.template, domain=domain, name=name)
    if rendered is None:
        if spec.kind == "fetch":
            return _fetch_error("unresolved", None)
        return _search_error("unresolved", None)

    if spec.kind == "fetch":
        return _fetch(organization_id, spec, rendered)
    return _search(spec, rendered)


def resolve_sources(
    organization_id: Any, *, domain: str | None, name: str | None, specs: Iterable[SourceSpec]
) -> dict[str, dict[str, Any]]:
    return {spec.key: fetch_source(organization_id, spec, domain=domain, name=name) for spec in specs}
