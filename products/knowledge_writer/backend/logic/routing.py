import re
from typing import Protocol

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


def is_writable_on_docs_site(github: GitHubReader | None, page_url: str) -> bool:
    page = DOCS_PAGE_PATTERN.match(page_url)
    if page is None:
        return True
    if github is None:
        return False
    try:
        return not is_published_from_repository(github, page.group(1))
    except SOURCE_LOOKUP_ERRORS:
        return False


def route_request(request: DocsRequest, *, team_id: int, github: GitHubReader | None) -> SectionRouting:
    writable_page_urls = tuple(
        page_url for page_url in request.suggested_page_urls if is_writable_on_docs_site(github, page_url)
    )
    sections = [section for section in map(docs_section, writable_page_urls) if section]
    return SectionRouting(section=sections[0] if sections else None, page_urls=writable_page_urls)
