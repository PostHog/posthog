from collections.abc import Sequence
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import structlog
from requests import RequestException

from posthog.dataclasses import frozen
from posthog.egress.firecrawl import (
    FirecrawlEgressBudgetExhausted,
    FirecrawlNotConfigured,
    FirecrawlScrapeFailed,
    ScrapeFormat,
    scrape,
)

logger = structlog.get_logger(__name__)

EGRESS_SOURCE = "tasks_domain_research"

SCRAPE_TIMEOUT: tuple[float, float] = (5.0, 45.0)

MARKDOWN_ONLY: tuple[ScrapeFormat, ...] = ("markdown",)

# Firecrawl runs an LLM pass for the summary, which roughly triples the scrape. Ask for it only
# where a person reads the summary back; the agent writes its own from the markdown.
WITH_SUMMARY: tuple[ScrapeFormat, ...] = ("markdown", "summary")

ResearchOutcome = Literal["scraped", "not_configured", "unreachable", "busy"]


@frozen
class DomainResearch:
    outcome: ResearchOutcome
    url: str
    title: str | None = None
    description: str | None = None
    markdown: str | None = None
    summary: str | None = None


def normalize_target(raw: str) -> str | None:
    candidate = raw.strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or "." not in parts.hostname:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def research_domain(url: str, *, formats: Sequence[ScrapeFormat] = MARKDOWN_ONLY) -> DomainResearch:
    try:
        scraped = scrape(url, source=EGRESS_SOURCE, formats=formats, timeout=SCRAPE_TIMEOUT)
    except FirecrawlNotConfigured:
        logger.warning("domain_research_firecrawl_not_configured")
        return DomainResearch(outcome="not_configured", url=url)
    except FirecrawlEgressBudgetExhausted:
        return DomainResearch(outcome="busy", url=url)
    except (FirecrawlScrapeFailed, RequestException):
        logger.warning("domain_research_scrape_failed", url=url)
        return DomainResearch(outcome="unreachable", url=url)

    return DomainResearch(
        outcome="scraped",
        url=url,
        title=scraped.title,
        description=scraped.description,
        markdown=scraped.markdown,
        summary=scraped.summary,
    )
