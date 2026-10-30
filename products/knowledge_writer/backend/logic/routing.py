import re
from typing import Literal, Protocol

import requests

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegrationError

from ..facade.contracts import DocsRequest

DOCS_SECTION_PATTERN = re.compile(r"^https://posthog\.com/docs/([a-z0-9-]+)")
DOCS_PAGE_PATTERN = re.compile(r"^https://posthog\.com/docs/(.+)$")
SOURCE_REPOSITORY = "PostHog/posthog"
SOURCE_LOOKUP_ERRORS = (
    requests.RequestException,
    GitHubIntegrationError,
    GitHubRateLimitError,
    GitHubEgressBudgetExhausted,
)
PUBLISHED_DOCS_DIRECTORY = "docs/published/docs"
PUBLISHED_DOCS_EXTENSIONS = (".md", ".mdx")


class GitHubReader(Protocol):
    def api_request(
        self,
        method: str,
        path: str,
        *,
        endpoint: str | None = None,
        params: dict[str, str | int] | None = None,
        priority: Priority | None = None,
    ) -> requests.Response: ...


@frozen
class SectionRouting:
    section: str | None
    page_urls: tuple[str, ...]
    is_every_page_in_source_repository: bool = False


def docs_section(page_url: str) -> str | None:
    match = DOCS_SECTION_PATTERN.match(page_url)
    return match.group(1) if match else None


def is_published_from_repository(github: GitHubReader, page_path: str, *, ref: str | None = None) -> bool:
    for extension in PUBLISHED_DOCS_EXTENSIONS:
        response = github.api_request(
            "GET",
            f"/repos/{SOURCE_REPOSITORY}/contents/{PUBLISHED_DOCS_DIRECTORY}/{page_path.strip('/')}{extension}",
            endpoint="/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref} if ref else None,
            priority=Priority.NORMAL,
        )
        if response.status_code == 200:
            return True
        if response.status_code != 404:
            response.raise_for_status()
    return False


PageLocation = Literal["docs_site", "source_repository", "unknown"]


def page_location(github: GitHubReader | None, page_url: str) -> PageLocation:
    page = DOCS_PAGE_PATTERN.match(page_url)
    if page is None:
        return "docs_site"
    if github is None:
        return "unknown"
    try:
        return "source_repository" if is_published_from_repository(github, page.group(1)) else "docs_site"
    except SOURCE_LOOKUP_ERRORS:
        return "unknown"


def is_from_source_repository(request: DocsRequest) -> bool:
    return request.source_url.lower().startswith(f"https://github.com/{SOURCE_REPOSITORY}/".lower())


def route_request(request: DocsRequest, *, team_id: int, github: GitHubReader | None) -> SectionRouting:
    location_by_page_url = {page_url: page_location(github, page_url) for page_url in request.suggested_page_urls}
    writable_page_urls = tuple(
        page_url for page_url, location in location_by_page_url.items() if location == "docs_site"
    )
    sections = [section for section in map(docs_section, writable_page_urls) if section]
    return SectionRouting(
        section=sections[0] if sections else None,
        page_urls=writable_page_urls,
        is_every_page_in_source_repository=is_from_source_repository(request)
        and bool(location_by_page_url)
        and all(location == "source_repository" for location in location_by_page_url.values()),
    )
