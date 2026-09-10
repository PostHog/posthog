"""Business rules for bounded public-web subscription research."""

from __future__ import annotations

import hashlib

from posthog.egress.firecrawl import (
    FirecrawlEgressBudgetExhausted,
    FirecrawlNotConfigured,
    FirecrawlPublicTargetRejected,
    FirecrawlRequestFailed,
    scrape_public_url,
    search_public_web,
)

from products.subscriptions.backend.facade.contracts import PublicResearchCitation, PublicResearchResult

_MAX_QUERY_CHARS = 500
_MAX_CITATIONS = 3
_MAX_TITLE_CHARS = 300
_MAX_EXCERPT_CHARS = 2_000


def run_public_research(query: str) -> PublicResearchResult:
    """Search once and scrape at most three provider-validated public results."""

    if not isinstance(query, str) or not query.strip() or len(query) > _MAX_QUERY_CHARS:
        raise ValueError("public research query must be between one and 500 characters")
    try:
        search_results = search_public_web(query.strip(), source="pulse_subscription")
    except FirecrawlNotConfigured:
        return PublicResearchResult(citations=(), degradation="not_configured")
    except FirecrawlEgressBudgetExhausted:
        return PublicResearchResult(citations=(), degradation="busy")
    except FirecrawlRequestFailed:
        return PublicResearchResult(citations=(), degradation="unavailable")

    citations: list[PublicResearchCitation] = []
    for search_result in search_results[:_MAX_CITATIONS]:
        try:
            scrape = scrape_public_url(search_result.url, source="pulse_subscription")
        except FirecrawlPublicTargetRejected:
            # A provider redirect that fails public-target validation is not evidence.
            continue
        except FirecrawlEgressBudgetExhausted:
            return PublicResearchResult(citations=tuple(citations), degradation="busy")
        except (FirecrawlNotConfigured, FirecrawlRequestFailed):
            return PublicResearchResult(citations=tuple(citations), degradation="unavailable")

        excerpt = _bounded_text(scrape.markdown, _MAX_EXCERPT_CHARS)
        if excerpt is None:
            continue
        title = _bounded_text(scrape.title, _MAX_TITLE_CHARS) or _bounded_text(search_result.title, _MAX_TITLE_CHARS)
        citations.append(
            PublicResearchCitation(
                id=f"web:{hashlib.sha256(scrape.url.encode('utf-8')).hexdigest()[:24]}",
                url=scrape.url,
                title=title or scrape.url,
                excerpt=excerpt,
            )
        )
    return PublicResearchResult(citations=tuple(citations))


def _bounded_text(value: str | None, maximum_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())[:maximum_length]
    return text or None
