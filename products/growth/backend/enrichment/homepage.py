"""Homepage content for AI-enrichment labels that opt in via EnrichmentPromptConfig.include_homepage.

Mirrors the degraded-path handling in products/tasks/backend/facade/domain_research.py: not
configured, unreachable, and busy are normal outcomes that classify_payload (enrichment/labels.py)
folds into a label's inputs, never exceptions that fail a label run.

Cached on OrganizationEnrichment.data["homepage"] rather than OrganizationEnrichmentFetch: that
archive's readers assume every payload is Harmonic data, and the cache is genuinely org-level
(any label with include_homepage=True reuses the same scrape), not label-level.
"""

import datetime as dt
from typing import Any, Literal

from django.utils import timezone

from requests import RequestException

from posthog.egress.firecrawl import (
    FirecrawlEgressBudgetExhausted,
    FirecrawlNotConfigured,
    FirecrawlScrapeFailed,
    scrape,
)
from posthog.exceptions_capture import capture_exception

from products.growth.backend.enrichment.writer import merge_into_record
from products.growth.backend.models import OrganizationEnrichment

EGRESS_SOURCE = "growth_ai_enrichment"

CACHE_TTL = dt.timedelta(days=30)

# Cached, and stored on the verdict's inputs, at up to this length. labels.py's own
# MAX_INPUT_VALUE_CHARS then bounds what actually reaches the prompt on top of this.
MAX_EXCERPT_CHARS = 8_000

HomepageFetchOutcome = Literal["scraped", "not_configured", "unreachable", "busy", "no_domain"]


def _cached_homepage(organization_id: Any, domain: str) -> dict[str, Any] | None:
    record = OrganizationEnrichment.objects.filter(organization_id=organization_id).only("data").first()
    if record is None:
        return None
    homepage = record.data.get("homepage")
    if not isinstance(homepage, dict) or not homepage.get("fetched_at"):
        return None
    # signup_domain_for_organization can resolve to a different domain later (a membership
    # backfill, an earlier-joined member added after the fact); a domain change must invalidate
    # the cache rather than serve a stale scrape of the org's former domain.
    if homepage.get("domain") != domain:
        return None
    fetched_at = dt.datetime.fromisoformat(homepage["fetched_at"])
    if timezone.now() - fetched_at > CACHE_TTL:
        return None
    return homepage


def _fields_from_record(record: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {"homepage_fetch_outcome": record["outcome"]}
    if record.get("summary"):
        fields["homepage_summary"] = record["summary"]
    if record.get("excerpt"):
        fields["homepage_excerpt"] = record["excerpt"]
    return fields


def homepage_input_fields(organization_id: Any, domain: str | None) -> dict[str, Any]:
    """Homepage-derived input fields for one org, cached across every label for CACHE_TTL.

    `domain` is the same signup domain a label already sends the LLM (see
    enrichment/labels.py's signup_domain_for_organization), not a second, independently
    resolved domain, so a label opting into homepage content still prompts about one company.

    Only a successful scrape is cached: a transient Firecrawl outage or an exhausted egress
    budget should not block homepage content for CACHE_TTL once the underlying cause clears.
    """
    if not domain:
        return {"homepage_fetch_outcome": "no_domain"}

    cached = _cached_homepage(organization_id, domain)
    if cached is not None:
        return _fields_from_record(cached)

    try:
        scraped = scrape(f"https://{domain}", source=EGRESS_SOURCE, formats=("markdown", "summary"))
    except FirecrawlNotConfigured:
        return {"homepage_fetch_outcome": "not_configured"}
    except FirecrawlEgressBudgetExhausted:
        return {"homepage_fetch_outcome": "busy"}
    except (FirecrawlScrapeFailed, RequestException):
        return {"homepage_fetch_outcome": "unreachable"}

    record = {
        "domain": domain,
        "fetched_at": timezone.now().isoformat(),
        "outcome": "scraped",
        "summary": scraped.summary,
        "excerpt": (scraped.markdown or "")[:MAX_EXCERPT_CHARS],
    }
    try:
        merge_into_record(str(organization_id), {"homepage": record})
    except Exception as e:
        # A cache-write failure must not undo an already-billed scrape or fail the label - same
        # reasoning as writer.archive_provider_fetch's own try/except around its archive write.
        capture_exception(e, {"organization_id": str(organization_id), "path": "homepage_input_fields"})
    return _fields_from_record(record)
