import re
import time
from html.parser import HTMLParser
from typing import TypedDict
from urllib.parse import urljoin, urlparse, urlunparse

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import ParseError as DefusedParseError

from products.web_analytics.backend.public_url_fetch import PublicUrlFetchError, fetch_public_url

_MAX_DISCOVERY_BYTES = 512 * 1024
_MAX_REDIRECTS = 2
_MAX_SITEMAP_CANDIDATES = 5
_MAX_DISCOVERY_SECONDS = 20.0
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class SiteDiscoveryResult(TypedDict):
    name: str
    domain: str
    source_urls: list[str]
    content_boundaries: list[str]
    sitemap_detected: bool
    warnings: list[str]


class _HomepageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sitemap_hrefs: list[str] = []
        self.title = ""
        self._inside_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "link" and "sitemap" in values.get("rel", "").lower().split():
            href = values.get("href", "").strip()
            if href:
                self.sitemap_hrefs.append(href)
        elif tag.lower() == "title":
            self._inside_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._inside_title = False

    def handle_data(self, data: str) -> None:
        if self._inside_title:
            self.title += data


def normalize_site_origin(raw_url: str) -> str:
    try:
        parsed = urlparse(raw_url.strip())
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as error:
        raise ValueError("Enter a valid http or https site URL.") from error
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        raise ValueError("Enter a valid http or https site URL.")
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and port != {"http": 80, "https": 443}[scheme]:
        netloc = f"{netloc}:{port}"
    return urlunparse((scheme, netloc, "", "", "", ""))


def _origin_key(url: str) -> tuple[str, str, int | None]:
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as error:
        raise PublicUrlFetchError("read", "The site returned an invalid URL.") from error
    if scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        raise PublicUrlFetchError("read", "The site returned an invalid URL.")
    effective_port = port if port is not None else {"http": 80, "https": 443}[scheme]
    return scheme, hostname, effective_port


def has_same_public_origin(first_url: str, second_url: str) -> bool:
    return _origin_key(first_url) == _origin_key(second_url)


def _fetch_text(url: str, *, origin: str, deadline: float) -> str:
    current_url = url
    for _ in range(_MAX_REDIRECTS + 1):
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            raise PublicUrlFetchError("deadline", "Site discovery took too long.")
        response = fetch_public_url(
            current_url,
            headers={
                "Accept": "text/html,application/xml,text/xml,text/plain;q=0.9,*/*;q=0.1",
                "User-Agent": "PostHog content site discovery",
            },
            max_bytes=_MAX_DISCOVERY_BYTES,
            deadline=deadline,
            connect_timeout_seconds=3.0,
            read_timeout_seconds=5.0,
        )
        if response.status_code in _REDIRECT_STATUSES:
            location = response.headers.get("Location") or response.headers.get("location")
            if not location:
                raise PublicUrlFetchError("read", "The site returned an invalid redirect.")
            next_url = urljoin(current_url, location)
            if _origin_key(next_url) != _origin_key(origin):
                raise PublicUrlFetchError("blocked", "The site redirected outside its origin.")
            current_url = next_url
            continue
        if response.status_code >= 400:
            raise PublicUrlFetchError("read", "The site response could not be used.")
        return response.body.decode("utf-8", errors="replace")
    raise PublicUrlFetchError("read", "The site returned too many redirects.")


def _sitemaps_from_robots(robots_text: str, *, origin: str) -> list[str]:
    sitemaps: list[str] = []
    for line in robots_text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "sitemap":
            try:
                candidate = urljoin(f"{origin}/", value.strip())
                if _origin_key(candidate) == _origin_key(origin):
                    sitemaps.append(candidate)
            except (ValueError, PublicUrlFetchError):
                continue
    return sitemaps


def _is_sitemap(xml_text: str) -> bool:
    try:
        root = ET.fromstring(xml_text)
    except (DefusedParseError, DefusedXmlException):
        return False
    root_name = root.tag.rsplit("}", 1)[-1].lower()
    return root_name in {"urlset", "sitemapindex"}


def _site_name(title: str, hostname: str) -> str:
    cleaned_title = re.sub(r"\s+", " ", title).strip()
    if cleaned_title:
        return re.split(r"\s+[|–—]\s+", cleaned_title, maxsplit=1)[0][:255]
    return hostname.removeprefix("www.")[:255]


def discover_site(raw_url: str) -> SiteDiscoveryResult:
    origin = normalize_site_origin(raw_url)
    deadline = time.monotonic() + _MAX_DISCOVERY_SECONDS
    hostname = urlparse(origin).hostname or origin
    candidates: list[str] = []
    title = ""

    try:
        robots_text = _fetch_text(f"{origin}/robots.txt", origin=origin, deadline=deadline)
        candidates.extend(_sitemaps_from_robots(robots_text, origin=origin))
    except PublicUrlFetchError:
        pass

    try:
        homepage_text = _fetch_text(f"{origin}/", origin=origin, deadline=deadline)
        parser = _HomepageParser()
        parser.feed(homepage_text)
        title = parser.title
        for href in parser.sitemap_hrefs:
            try:
                candidates.append(urljoin(f"{origin}/", href))
            except ValueError:
                continue
    except PublicUrlFetchError:
        pass

    candidates.extend(
        [
            f"{origin}/sitemap.xml",
            f"{origin}/sitemap_index.xml",
            f"{origin}/sitemap-index.xml",
        ]
    )
    unique_candidates: list[str] = []
    for candidate in candidates:
        try:
            if _origin_key(candidate) == _origin_key(origin) and candidate not in unique_candidates:
                unique_candidates.append(candidate)
        except (ValueError, PublicUrlFetchError):
            continue
        if len(unique_candidates) == _MAX_SITEMAP_CANDIDATES:
            break

    detected_sitemaps: list[str] = []
    for candidate in unique_candidates:
        if time.monotonic() >= deadline:
            break
        try:
            if _is_sitemap(_fetch_text(candidate, origin=origin, deadline=deadline)):
                detected_sitemaps.append(candidate)
        except PublicUrlFetchError:
            continue

    sitemap_detected = bool(detected_sitemaps)
    source_urls = detected_sitemaps or [f"{origin}/sitemap.xml"]
    warnings = [] if sitemap_detected else ["We couldn't verify a sitemap. Review the suggested URL before saving."]
    return {
        "name": _site_name(title, hostname),
        "domain": origin,
        "source_urls": source_urls,
        "content_boundaries": ["/"],
        "sitemap_detected": sitemap_detected,
        "warnings": warnings,
    }
