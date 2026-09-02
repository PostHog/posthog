"""Company web pages that AI-enrichment labels read via a `pages.<type>.<key>` input field.

Cached on OrganizationEnrichment.data["pages"] keyed by page type, and kept out of
EnrichmentFields so page markdown never projects onto group properties. Fetching happens in the
command and lab layers before classify_payload runs; labels.py only reads the store it is handed.
A degraded outcome is a normal record here, never an exception: an unreachable page is cached
because it is a fact about the domain, while a configuration or budget problem is not, so it can
clear before CACHE_TTL. Page copy is public, so it skips labels.to_domain's email reduction.
"""

import datetime as dt
from collections.abc import Iterable
from typing import Any, Literal

from django.utils import timezone

from requests import RequestException

from posthog.egress.firecrawl import (
    FirecrawlEgressBudgetExhausted,
    FirecrawlNotConfigured,
    FirecrawlScrapeFailed,
    scrape,
)
from posthog.egress.limiter.policies import Priority
from posthog.exceptions_capture import capture_exception

from products.growth.backend.enrichment.writer import merge_into_record
from products.growth.backend.models import OrganizationEnrichment

EGRESS_SOURCE = "growth_ai_enrichment"

CACHE_TTL = dt.timedelta(days=30)

# Namespace prefix for input_fields paths resolved from the page store below, rather than naming
# a dotted path into the archived Harmonic payload — kept in sync with labels.PAGES_INPUT_PREFIX.
INPUT_FIELD_PREFIX = "pages."

# Cached, and stored on the verdict's inputs, at up to this length. labels.py's own
# MAX_INPUT_VALUE_CHARS then bounds what actually reaches the prompt on top of this.
MAX_MARKDOWN_CHARS = 8_000

PageFetchError = Literal["not_configured", "unreachable", "busy", "no_domain", "unsupported_type"]


def page_types_from_input_fields(input_fields: Iterable[str]) -> set[str]:
    """Every distinct page type a config's input_fields names, e.g. {"pages.home.markdown",
    "pages.pricing.markdown"} -> {"home", "pricing"}. A malformed entry (wrong segment count) is
    skipped here — labels.validate_input_fields is what rejects those, before a config can ever
    reach a runner, so this function only ever sees well-formed paths in practice."""
    types = set()
    for path in input_fields:
        if not path.startswith(INPUT_FIELD_PREFIX):
            continue
        parts = path.split(".")
        if len(parts) == 3 and parts[1]:
            types.add(parts[1])
    return types


def _error_record(domain: str | None, error: PageFetchError, url: str | None = None) -> dict[str, Any]:
    return {
        "url": url,
        "markdown": None,
        "fetched_at": timezone.now().isoformat(),
        "domain": domain,
        "error": error,
    }


def _cached_page(organization_id: Any, domain: str, page_type: str) -> dict[str, Any] | None:
    record = OrganizationEnrichment.objects.filter(organization_id=organization_id).only("data").first()
    if record is None:
        return None
    pages = record.data.get("pages")
    if not isinstance(pages, dict):
        return None
    page = pages.get(page_type)
    if not isinstance(page, dict) or not page.get("fetched_at"):
        return None
    # A domain change (a membership backfill, an earlier-joined member added after the fact) must
    # invalidate the cache rather than serve a stale scrape of the org's former domain — same
    # reasoning as homepage.py's _cached_homepage.
    if page.get("domain") != domain:
        return None
    fetched_at = dt.datetime.fromisoformat(page["fetched_at"])
    if timezone.now() - fetched_at > CACHE_TTL:
        return None
    return page


def _cache_page(organization_id: Any, page_type: str, record: dict[str, Any]) -> None:
    try:
        merge_into_record(
            str(organization_id),
            lambda data: {"pages": {**data.get("pages", {}), page_type: record}},
        )
    except Exception as e:
        # A cache-write failure must not undo an already-billed scrape or fail the label — same
        # reasoning as writer.archive_provider_fetch's own try/except around its archive write.
        capture_exception(
            e, {"organization_id": str(organization_id), "path": "pages.fetch_page", "page_type": page_type}
        )


def _resolve_url(page_type: str, domain: str) -> str | None:
    """The URL to scrape for a page type, or None for a type this module doesn't yet resolve."""
    if page_type == "home":
        return f"https://{domain}"
    if page_type == "pricing":
        return f"https://{domain}/pricing"
    return None


def fetch_page(organization_id: Any, domain: str | None, page_type: str) -> dict[str, Any]:
    """One page's content for one org, cached across every label for CACHE_TTL. Never raises: a
    Firecrawl outage or an exhausted egress budget degrades to an "error" record rather than
    failing whatever label asked for this page.

    `domain` is the same signup domain a label already sends the LLM (see
    labels.signup_domain_for_organization), not a second, independently resolved domain.
    """
    if not domain:
        return _error_record(None, "no_domain")

    cached = _cached_page(organization_id, domain, page_type)
    if cached is not None:
        return cached

    url = _resolve_url(page_type, domain)
    if url is None:
        # Not cached: adding resolution for a new page type must take effect on the next run,
        # not wait out CACHE_TTL.
        return _error_record(domain, "unsupported_type")

    try:
        scraped = scrape(url, source=EGRESS_SOURCE, formats=("markdown",), priority=Priority.BATCH)
    except FirecrawlNotConfigured:
        return _error_record(domain, "not_configured", url=url)
    except FirecrawlEgressBudgetExhausted:
        # Not cached: the shared budget refilling within CACHE_TTL must not stay pinned to a
        # stale "no" for a month.
        return _error_record(domain, "busy", url=url)
    except (FirecrawlScrapeFailed, RequestException):
        # Cached, unlike the branches above: a dead or 404ing page is a fact about the domain,
        # not a transient operational condition, so the runner must not refetch it every day.
        record = _error_record(domain, "unreachable", url=url)
        _cache_page(organization_id, page_type, record)
        return record

    record = {
        "url": url,
        "markdown": (scraped.markdown or "")[:MAX_MARKDOWN_CHARS],
        "fetched_at": timezone.now().isoformat(),
        "domain": domain,
    }
    _cache_page(organization_id, page_type, record)
    return record


def ensure_pages_fetched(organization_id: Any, domain: str | None, page_types: Iterable[str]) -> dict[str, Any]:
    """Fetch (or reuse a still-fresh cached) page for every named type, and return the org's
    resulting page store keyed by type — the shape classify_payload's `pages` argument expects.

    Called once per org from the command layer before classify_payload runs. Never raises, since
    fetch_page never raises: a Firecrawl outage degrades to a missing pages.* input for this org,
    never a skipped org or a tripped circuit breaker.
    """
    return {page_type: fetch_page(organization_id, domain, page_type) for page_type in page_types}
