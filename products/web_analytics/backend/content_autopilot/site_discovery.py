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
_DEFAULT_PORTS = {"http": 80, "https": 443}


class SiteDiscoveryResult(TypedDict):
    name: str
    domain: str
    source_urls: list[str]
    content_boundaries: list[str]
    sitemap_detected: bool
    warnings: list[str]


class _SiteNameParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.og_site_name = ""
        self.title = ""
        self._inside_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered == "title":
            self._inside_title = True
        elif lowered == "meta" and not self.og_site_name:
            values = {key.lower(): value or "" for key, value in attrs}
            if values.get("property", "").strip().lower() == "og:site_name":
                self.og_site_name = values.get("content", "")

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
    if scheme not in _DEFAULT_PORTS or not hostname or parsed.username or parsed.password:
        raise ValueError("Enter a valid http or https site URL.")
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        netloc = f"{netloc}:{port}"
    return urlunparse((scheme, netloc, "", "", "", ""))


def _origin_key(url: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return None
    if scheme not in _DEFAULT_PORTS or not hostname or parsed.username or parsed.password:
        return None
    return scheme, hostname, port if port is not None else _DEFAULT_PORTS[scheme]


def has_same_public_origin(first_url: str, second_url: str) -> bool:
    key = _origin_key(first_url)
    return key is not None and key == _origin_key(second_url)


def _fetch_text(url: str, *, deadline: float) -> str:
    current_url = url
    for _ in range(_MAX_REDIRECTS + 1):
        if time.monotonic() >= deadline:
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
            location = response.headers.get("location")
            if not location:
                raise PublicUrlFetchError("read", "The site returned an invalid redirect.")
            current_url = urljoin(current_url, location)
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
            candidate = urljoin(f"{origin}/", value.strip())
            if has_same_public_origin(candidate, origin):
                sitemaps.append(candidate)
    return sitemaps


def _is_sitemap(xml_text: str) -> bool:
    try:
        root = ET.fromstring(xml_text)
    except (DefusedParseError, DefusedXmlException):
        return False
    root_name = root.tag.rsplit("}", 1)[-1].lower()
    return root_name in {"urlset", "sitemapindex"}


def _site_name(og_site_name: str, title: str, hostname: str) -> str:
    declared_name = re.sub(r"\s+", " ", og_site_name).strip()
    if declared_name:
        return declared_name[:255]
    cleaned_title = re.sub(r"\s+", " ", title).strip()
    if cleaned_title:
        return re.split(r"\s+[|–—]\s+", cleaned_title, maxsplit=1)[0][:255]
    return hostname.removeprefix("www.")[:255]


def discover_site(raw_url: str) -> SiteDiscoveryResult:
    origin = normalize_site_origin(raw_url)
    deadline = time.monotonic() + _MAX_DISCOVERY_SECONDS
    hostname = urlparse(origin).hostname or origin
    candidates: list[str] = []
    og_site_name = ""
    title = ""

    try:
        robots_text = _fetch_text(f"{origin}/robots.txt", deadline=deadline)
        candidates.extend(_sitemaps_from_robots(robots_text, origin=origin))
    except PublicUrlFetchError:
        pass

    try:
        parser = _SiteNameParser()
        parser.feed(_fetch_text(f"{origin}/", deadline=deadline))
        og_site_name = parser.og_site_name
        title = parser.title
    except PublicUrlFetchError:
        pass

    candidates.extend(
        [
            f"{origin}/sitemap.xml",
            f"{origin}/sitemap_index.xml",
            f"{origin}/sitemap-index.xml",
        ]
    )
    unique_candidates = list(dict.fromkeys(candidates))[:_MAX_SITEMAP_CANDIDATES]

    detected_sitemaps: list[str] = []
    for candidate in unique_candidates:
        if time.monotonic() >= deadline:
            break
        try:
            if _is_sitemap(_fetch_text(candidate, deadline=deadline)):
                detected_sitemaps.append(candidate)
        except PublicUrlFetchError:
            continue

    sitemap_detected = bool(detected_sitemaps)
    source_urls = detected_sitemaps or [f"{origin}/sitemap.xml"]
    warnings = [] if sitemap_detected else ["We couldn't verify a sitemap. Review the suggested URL before saving."]
    return {
        "name": _site_name(og_site_name, title, hostname),
        "domain": origin,
        "source_urls": source_urls,
        "content_boundaries": ["/"],
        "sitemap_detected": sitemap_detected,
        "warnings": warnings,
    }
