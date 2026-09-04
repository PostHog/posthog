"""Company web pages that AI-enrichment labels read via a `pages.<type>.<key>` input field.

OrganizationEnrichment.data["pages"] holds one outcome record per page type (url, domain,
fetched_at, source, error) for provenance, never the page text; only an unreachable outcome
within CACHE_TTL skips a re-fetch."""

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
    scrape,
)
from posthog.egress.limiter.policies import Priority
from posthog.exceptions_capture import capture_exception

from products.growth.backend.enrichment.labels import MAX_INPUT_VALUE_CHARS, pages_path
from products.growth.backend.enrichment.writer import merge_into_record
from products.growth.backend.models import OrganizationEnrichment

logger = structlog.get_logger(__name__)

EGRESS_SOURCE = "growth_ai_enrichment"

CACHE_TTL = dt.timedelta(days=30)

PageFetchError = Literal["not_configured", "unreachable", "busy", "no_domain", "unsupported_type"]

# Retryable next run, so a caller computing a permanent verdict must defer the org instead of
# treating missing page content as data.
TRANSIENT_PAGE_ERRORS = frozenset({"not_configured", "busy"})


def page_types_from_input_fields(input_fields: Iterable[str]) -> set[str]:
    types = set()
    for path in input_fields:
        parsed = pages_path(path)
        if parsed is not None:
            types.add(parsed.page_type)
    return types


def _error_record(domain: str | None, error: PageFetchError, url: str | None = None) -> dict[str, Any]:
    return {
        "url": url,
        "fetched_at": timezone.now().isoformat(),
        "domain": domain,
        "error": error,
        "source": "scrape",
    }


def _cached_unreachable_page(organization_id: Any, domain: str, page_type: str) -> dict[str, Any] | None:
    record = OrganizationEnrichment.objects.filter(organization_id=organization_id).only("data").first()
    if record is None:
        return None
    pages = record.data.get("pages")
    if not isinstance(pages, dict):
        return None
    page = pages.get(page_type)
    if not isinstance(page, dict) or not page.get("fetched_at"):
        return None
    # A domain change must invalidate the cache rather than serve a stale scrape of the org's former domain.
    if page.get("domain") != domain:
        return None
    # A stored success is provenance only, never a short-circuit: the text can change, and there's
    # no signal here that it hasn't.
    if page.get("error") != "unreachable":
        return None
    try:
        fetched_at = dt.datetime.fromisoformat(page["fetched_at"])
        if timezone.now() - fetched_at > CACHE_TTL:
            return None
    except (ValueError, TypeError):
        # An unparsable or naive timestamp is indistinguishable from a stale record, so treat it as a miss.
        return None
    return page


def _cache_page(organization_id: Any, page_type: str, record: dict[str, Any]) -> None:
    try:
        merge_into_record(
            str(organization_id),
            lambda data: {"pages": {**data.get("pages", {}), page_type: record}},
        )
    except Exception as e:
        # A cache-write failure must not undo an already-billed scrape or fail the label.
        capture_exception(
            e, {"organization_id": str(organization_id), "path": "pages.fetch_page", "page_type": page_type}
        )


def _resolve_url(page_type: str, domain: str) -> str | None:
    if page_type == "home":
        return f"https://{domain}"
    if page_type == "pricing":
        return f"https://{domain}/pricing"
    return None


def fetch_page(organization_id: Any, domain: str | None, page_type: str) -> dict[str, Any]:
    """Fetches a page for one org, skipping the scrape only when the last attempt was cached as
    unreachable within CACHE_TTL. A successful fetch is always repeated for its text. Never
    raises, degrading a Firecrawl failure to an "error" record instead of failing the label."""
    if not domain:
        return _error_record(None, "no_domain")

    cached = _cached_unreachable_page(organization_id, domain, page_type)
    if cached is not None:
        return {**cached, "source": "cache"}

    url = _resolve_url(page_type, domain)
    if url is None:
        # Not cached, so adding a resolver for a new page type takes effect next run instead of
        # waiting out CACHE_TTL.
        return _error_record(domain, "unsupported_type")

    try:
        scraped = scrape(url, source=EGRESS_SOURCE, formats=("markdown",), priority=Priority.BATCH)
    except FirecrawlNotConfigured:
        logger.warning("enrichment_page_fetch_degraded", error="not_configured", page_type=page_type, url=url)
        return _error_record(domain, "not_configured", url=url)
    except FirecrawlEgressBudgetExhausted:
        # Not cached, since the shared budget can refill before CACHE_TTL elapses.
        logger.warning("enrichment_page_fetch_degraded", error="busy", page_type=page_type, url=url)
        return _error_record(domain, "busy", url=url)
    except (FirecrawlScrapeFailed, RequestException):
        # A gateway error, rate limit, or timeout looks identical to an outage here, so it must not
        # be cached as unreachable.
        logger.warning("enrichment_page_fetch_degraded", error="busy", page_type=page_type, url=url)
        return _error_record(domain, "busy", url=url)

    status = scraped.status_code
    bad_status = status is not None and status != 304 and not (200 <= status < 300)
    if bad_status or not scraped.markdown:
        # Cached: a 404/403 or an empty page is a fact about the domain, not a transient condition.
        record = _error_record(domain, "unreachable", url=url)
        _cache_page(organization_id, page_type, record)
        return record

    stored = {
        "url": url,
        "fetched_at": timezone.now().isoformat(),
        "domain": domain,
        "source": "scrape",
    }
    _cache_page(organization_id, page_type, stored)
    return {**stored, "markdown": scraped.markdown[:MAX_INPUT_VALUE_CHARS]}


def ensure_pages_fetched(organization_id: Any, domain: str | None, page_types: Iterable[str]) -> dict[str, Any]:
    """Fetches every named page type via fetch_page and returns them keyed by type; never raises,
    since fetch_page never raises."""
    return {page_type: fetch_page(organization_id, domain, page_type) for page_type in page_types}
