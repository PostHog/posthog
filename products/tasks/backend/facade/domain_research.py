from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import structlog
from requests import RequestException

from posthog.dataclasses import frozen
from posthog.egress.firecrawl import (
    FirecrawlEgressBudgetExhausted,
    FirecrawlNotConfigured,
    FirecrawlScrapeFailed,
    scrape,
)

logger = structlog.get_logger(__name__)

EGRESS_SOURCE = "tasks_domain_research"

SCRAPE_TIMEOUT: tuple[float, float] = (5.0, 20.0)

ResearchOutcome = Literal["scraped", "not_configured", "unreachable", "busy"]


@frozen
class DomainResearch:
    outcome: ResearchOutcome
    url: str
    title: str | None = None
    description: str | None = None
    markdown: str | None = None


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


def research_domain(url: str) -> DomainResearch:
    try:
        scraped = scrape(url, source=EGRESS_SOURCE, formats=("markdown",), timeout=SCRAPE_TIMEOUT)
    except FirecrawlNotConfigured:
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
    )
