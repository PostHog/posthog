import re

from posthog.dataclasses import frozen

from products.business_knowledge.backend.facade import api as business_knowledge_facade

from ..facade.contracts import DocsRequest

DOCS_SECTION_PATTERN = re.compile(r"^https://posthog\.com/docs/([a-z0-9-]+)")
SEARCH_QUERY_MAX_LENGTH = 500
MAX_SUGGESTED_PAGES = 3


@frozen
class SectionRouting:
    section: str | None
    page_urls: tuple[str, ...]


def docs_section(page_url: str) -> str | None:
    match = DOCS_SECTION_PATTERN.match(page_url)
    return match.group(1) if match else None


def route_request(request: DocsRequest, *, team_id: int) -> SectionRouting:
    page_urls = request.suggested_page_urls
    if not page_urls:
        query = f"{request.trigger_instructions} {request.evidence}"[:SEARCH_QUERY_MAX_LENGTH]
        hits = business_knowledge_facade.search_knowledge(team_id=team_id, query=query)
        docs_urls = [hit.url for hit in hits if docs_section(hit.url)]
        page_urls = tuple(dict.fromkeys(docs_urls))[:MAX_SUGGESTED_PAGES]
    sections = [section for section in map(docs_section, page_urls) if section]
    return SectionRouting(section=sections[0] if sections else None, page_urls=page_urls)
