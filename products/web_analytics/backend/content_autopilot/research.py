import re
import time
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import urlparse

from posthog.dataclasses import frozen
from posthog.egress.firecrawl.client import (
    MAX_SEARCH_QUERY_CHARS,
    FirecrawlNotConfigured,
    FirecrawlScrapeFailed,
    FirecrawlSearchFailed,
    scrape,
    search,
)
from posthog.egress.firecrawl.transport import FirecrawlEgressBudgetExhausted
from posthog.egress.limiter.policies import Priority
from posthog.security.llm_prompt_sanitization import strip_llm_framing_markers
from posthog.security.url_validation import strip_userinfo

from products.web_analytics.backend.content_autopilot.site_discovery import has_same_public_site, site_host
from products.web_analytics.backend.public_url_fetch import PublicUrlFetchError, fetch_public_url

MAX_DOCUMENT_CHARS = 40_000
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_COMPETITOR_PAGES = 4
MAX_NAMED_COMPETITOR_PAGES = 3
MAX_LINK_CANDIDATES = 60
FETCH_SECONDS = 20.0
FIRECRAWL_SOURCE = "content_autopilot"
MAX_SITE_SEARCH_RESULTS = 10

DocumentOrigin = Literal["site", "competitor"]


@frozen
class SourceDocument:
    url: str
    title: str
    text: str
    origin: DocumentOrigin

    def to_dict(self) -> dict[str, str]:
        return {"url": self.url, "title": self.title, "text": self.text, "origin": self.origin}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SourceDocument":
        origin: DocumentOrigin = "site" if value.get("origin") == "site" else "competitor"
        return cls(url=str(value["url"]), title=str(value.get("title", "")), text=str(value["text"]), origin=origin)


@frozen
class ResearchBundle:
    prompt: str
    target_url: str
    documents: tuple[SourceDocument, ...]
    link_candidates: tuple[str, ...]
    skipped: tuple[str, ...]

    @property
    def site_documents(self) -> tuple[SourceDocument, ...]:
        return tuple(document for document in self.documents if document.origin == "site")

    @property
    def competitor_documents(self) -> tuple[SourceDocument, ...]:
        return tuple(document for document in self.documents if document.origin == "competitor")

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "target_url": self.target_url,
            "documents": [document.to_dict() for document in self.documents],
            "link_candidates": list(self.link_candidates),
            "skipped": list(self.skipped),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ResearchBundle":
        return cls(
            prompt=str(value.get("prompt", "")),
            target_url=str(value.get("target_url", "")),
            documents=tuple(SourceDocument.from_dict(document) for document in value.get("documents", [])),
            link_candidates=tuple(str(url) for url in value.get("link_candidates", [])),
            skipped=tuple(str(note) for note in value.get("skipped", [])),
        )


@frozen
class _PageText:
    title: str
    text: str


@frozen
class _FetchedBody:
    content_type: str
    body: str


class _TextExtractor(HTMLParser):
    _SKIPPED_TAGS = frozenset({"script", "style", "noscript", "nav", "header", "footer", "aside", "svg", "form"})
    _BLOCK_TAGS = frozenset({"p", "div", "section", "article", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6"})
    _MAIN_TAGS = frozenset({"main", "article"})

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._parts: list[str] = []
        self._main_parts: list[str] = []
        self._skip_depth = 0
        self._main_depth = 0
        self._inside_title = False

    def _append(self, text: str) -> None:
        self._parts.append(text)
        if self._main_depth:
            self._main_parts.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._inside_title = True
        elif tag in self._BLOCK_TAGS or tag in self._MAIN_TAGS:
            if tag in self._MAIN_TAGS:
                self._main_depth += 1
            self._append("\n")
            if tag in {"h1", "h2", "h3"}:
                self._append("#" * int(tag[1]) + " ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._inside_title = False
        elif tag in self._MAIN_TAGS and self._main_depth:
            self._main_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._inside_title:
            self.title += data
        elif not self._skip_depth and data.strip():
            self._append(data.strip() + " ")

    @property
    def text(self) -> str:
        parts = self._main_parts if any(part.strip() for part in self._main_parts) else self._parts
        lines = (line.strip() for line in "".join(parts).splitlines())
        return "\n".join(line for line in lines if line)


def html_to_text(html: str) -> _PageText:
    extractor = _TextExtractor()
    extractor.feed(html)
    return _PageText(title=extractor.title.strip(), text=extractor.text)


def _fetch(url: str, accept: str) -> _FetchedBody | None:
    try:
        response = fetch_public_url(
            strip_userinfo(url),
            headers={"Accept": accept, "User-Agent": "PostHog content research"},
            max_bytes=MAX_DOCUMENT_BYTES,
            deadline=time.monotonic() + FETCH_SECONDS,
            connect_timeout_seconds=3.0,
            read_timeout_seconds=15.0,
        )
    except PublicUrlFetchError:
        return None
    if not 200 <= response.status_code < 300:
        return None
    return _FetchedBody(
        content_type=response.headers.get("content-type", ""), body=response.body.decode("utf-8", errors="replace")
    )


def _markdown_twin(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/index"
    return parsed._replace(path=f"{path}.md", query="", fragment="").geturl()


def _page_path(url: str) -> str:
    return urlparse(url).path.rstrip("/") or "/"


def _page_key(url: str) -> str:
    return f"{site_host(url)}{_page_path(url)}"


def _clean(text: str) -> str:
    return strip_llm_framing_markers(text, MAX_DOCUMENT_CHARS)


def _links_to_page(markdown: str, url: str) -> bool:
    targets = [re.escape(url.rstrip("/"))]
    if (path := _page_path(url)) != "/":
        targets.append(r"(?<![\w.:/-])" + re.escape(path))
    return re.search(f"(?:{'|'.join(targets)})/?(?![\\w/.-])", markdown) is not None


def _without_preamble(markdown: str) -> str:
    lines = markdown.splitlines()
    h1 = next((index for index, line in enumerate(lines) if line.startswith("# ")), None)
    if h1 is None or not all(not line.strip() or line.startswith(">") for line in lines[:h1]):
        return markdown
    return "\n".join(lines[h1:])


def _fetch_html_document(url: str, origin: DocumentOrigin) -> SourceDocument | None:
    page = _fetch(url, "text/html,application/xhtml+xml;q=0.9")
    if page is None:
        return None
    extracted = html_to_text(page.body)
    if not extracted.text:
        return None
    return SourceDocument(url=url, title=extracted.title, text=_clean(extracted.text), origin=origin)


def fetch_site_page(url: str) -> SourceDocument | None:
    twin_document: SourceDocument | None = None
    twin = _fetch(_markdown_twin(url), "text/markdown,text/plain;q=0.9")
    if twin is not None and "html" not in twin.content_type.lower() and twin.body.strip():
        body = _without_preamble(twin.body)
        first_heading = next((line[2:] for line in body.splitlines() if line.startswith("# ")), "")
        twin_document = SourceDocument(url=url, title=first_heading.strip(), text=_clean(body), origin="site")
        if not _links_to_page(twin.body, url):
            return twin_document
    page_document = _fetch_html_document(url, "site")
    if page_document is None or (twin_document is not None and len(twin_document.text) >= len(page_document.text)):
        return twin_document
    return page_document


def fetch_competitor_page(url: str) -> SourceDocument | None:
    try:
        scraped = scrape(url, source=FIRECRAWL_SOURCE, formats=("markdown",), priority=Priority.BATCH)
        if scraped.markdown:
            return SourceDocument(
                url=url, title=scraped.title or "", text=_clean(scraped.markdown), origin="competitor"
            )
    except (FirecrawlNotConfigured, FirecrawlScrapeFailed, FirecrawlEgressBudgetExhausted):
        pass
    return _fetch_html_document(url, "competitor")


def search_site_pages(prompt: str, *, site_origin: str, site_urls: list[str]) -> list[str]:
    host = site_host(site_origin)
    if not host:
        return []
    try:
        found = search(
            f"site:{host} {prompt}"[:MAX_SEARCH_QUERY_CHARS],
            source=FIRECRAWL_SOURCE,
            limit=MAX_SITE_SEARCH_RESULTS,
            priority=Priority.BATCH,
        )
    except (FirecrawlNotConfigured, FirecrawlSearchFailed, FirecrawlEgressBudgetExhausted):
        return []
    by_page = {_page_key(url): url for url in reversed(site_urls)}
    pages = [
        by_page.get(_page_key(result.url), result.url)
        for result in found.results
        if has_same_public_site(result.url, site_origin)
    ]
    return list(dict.fromkeys(pages))


def gather_research(
    *,
    prompt: str,
    target_url: str,
    competitor_urls: list[str],
    site_origin: str,
    link_candidates: list[str],
) -> ResearchBundle:
    skipped: list[str] = []
    documents: list[SourceDocument] = []

    if target_url:
        document = fetch_site_page(target_url)
        if document is None:
            skipped.append(f"Couldn't read the site page {target_url}.")
        else:
            documents.append(document)

    competitors = [url for url in competitor_urls if not has_same_public_site(url, site_origin)]
    for url in competitors[:MAX_COMPETITOR_PAGES]:
        document = fetch_competitor_page(url)
        if document is None:
            skipped.append(f"Couldn't read the cited page {url}.")
            continue
        documents.append(document)

    return ResearchBundle(
        prompt=prompt,
        target_url=target_url,
        documents=tuple(documents),
        link_candidates=tuple(link_candidates[:MAX_LINK_CANDIDATES]),
        skipped=tuple(skipped),
    )


def fetch_named_competitor_pages(
    urls: list[str], *, site_origin: str, research: ResearchBundle
) -> tuple[list[SourceDocument], list[str]]:
    known_pages = {_page_key(document.url) for document in research.documents}
    documents: list[SourceDocument] = []
    skipped: list[str] = []
    for url in urls[:MAX_NAMED_COMPETITOR_PAGES]:
        page = _page_key(url)
        if not site_host(url) or page in known_pages or has_same_public_site(url, site_origin):
            continue
        document = fetch_competitor_page(url)
        if document is None:
            skipped.append(f"Couldn't read the competitor page {url}.")
            continue
        documents.append(document)
        known_pages.add(page)
    return documents, skipped
