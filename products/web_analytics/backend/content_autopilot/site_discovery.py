import re
import time
from html.parser import HTMLParser
from typing import TypedDict
from urllib.parse import urljoin, urlparse, urlunparse

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import ParseError as DefusedParseError

from posthog.dataclasses import frozen
from posthog.security.llm_prompt_sanitization import sanitize_user_text
from posthog.security.url_validation import has_authority_bypass_chars, strip_userinfo

from products.web_analytics.backend.public_url_fetch import (
    PUBLIC_URL_REDIRECT_STATUSES,
    PublicUrlFetchError,
    fetch_public_url,
)

_MAX_DISCOVERY_BYTES = 512 * 1024
_MAX_REDIRECTS = 2
_MAX_SITEMAP_CANDIDATES = 5
_MAX_DISCOVERY_REQUESTS = 12
_MAX_DISCOVERY_SECONDS = 20.0
_DEFAULT_PORTS = {"http": 80, "https": 443}
_MAX_SITE_NAME_LENGTH = 255
_CONVENTIONAL_SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml")


class SiteDiscoveryResult(TypedDict):
    name: str
    domain: str
    source_urls: list[str]
    content_boundaries: list[str]
    sitemap_detected: bool
    warnings: list[str]


@frozen
class _FetchedText:
    text: str
    url: str


class _RequestBudget:
    def __init__(self, limit: int) -> None:
        self.remaining = limit

    def spend(self) -> None:
        if self.remaining <= 0:
            raise PublicUrlFetchError("read", "Site discovery made too many requests.")
        self.remaining -= 1


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
    invalid = ValueError("Enter a valid http or https site URL.")
    stripped = raw_url.strip()
    if has_authority_bypass_chars(stripped):
        raise invalid
    try:
        parsed = urlparse(stripped)
        hostname = (parsed.hostname or "").lower().removesuffix(".")
        port = parsed.port
    except ValueError as error:
        raise invalid from error
    scheme = parsed.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not hostname or parsed.username or parsed.password or port == 0:
        raise invalid
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        netloc = f"{netloc}:{port}"
    return urlunparse((scheme, netloc, "", "", "", ""))


def _origin_key(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return None
    if scheme not in _DEFAULT_PORTS or not hostname or parsed.username or parsed.password:
        return None
    return f"{scheme}://{hostname.removesuffix('.')}:{port if port is not None else _DEFAULT_PORTS[scheme]}"


def has_same_public_origin(first_url: str, second_url: str) -> bool:
    key = _origin_key(first_url)
    return key is not None and key == _origin_key(second_url)


def _public_host(url: str) -> str:
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower().removesuffix(".")
    except ValueError:
        return ""
    if scheme not in _DEFAULT_PORTS or not hostname or parsed.username or parsed.password:
        return ""
    return hostname


def has_same_public_site(first_url: str, second_url: str) -> bool:
    first = _public_host(first_url).removeprefix("www.")
    second = _public_host(second_url).removeprefix("www.")
    if not first or not second:
        return False
    return first == second or first.endswith(f".{second}") or second.endswith(f".{first}")


def _fetch_text(url: str, *, deadline: float, budget: _RequestBudget) -> _FetchedText:
    current_url = strip_userinfo(url)
    for _ in range(_MAX_REDIRECTS + 1):
        if time.monotonic() >= deadline:
            raise PublicUrlFetchError("deadline", "Site discovery took too long.")
        budget.spend()
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
        if response.status_code in PUBLIC_URL_REDIRECT_STATUSES:
            location = response.headers.get("location")
            if not location:
                raise PublicUrlFetchError("read", "The site returned an invalid redirect.")
            target = strip_userinfo(urljoin(current_url, location))
            if not has_same_public_site(target, url):
                raise PublicUrlFetchError("blocked", "The site redirected away from its own domain.")
            current_url = target
            continue
        if response.status_code < 200 or response.status_code >= 300:
            raise PublicUrlFetchError("read", "The site response could not be used.")
        return _FetchedText(text=response.body.decode("utf-8", errors="replace"), url=current_url)
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


def _verified_sitemaps(candidates: list[str], *, deadline: float, budget: _RequestBudget) -> list[str]:
    verified: list[str] = []
    for candidate in candidates:
        if time.monotonic() >= deadline:
            break
        try:
            fetched = _fetch_text(candidate, deadline=deadline, budget=budget)
        except PublicUrlFetchError:
            continue
        if _is_sitemap(fetched.text):
            verified.append(fetched.url)
    return list(dict.fromkeys(verified))


def _site_name(og_site_name: str, title: str, hostname: str) -> str:
    declared_name = sanitize_user_text(og_site_name, _MAX_SITE_NAME_LENGTH)
    if declared_name:
        return declared_name
    cleaned_title = sanitize_user_text(title, _MAX_SITE_NAME_LENGTH)
    if cleaned_title:
        return re.split(r"\s+[|–—]\s+", cleaned_title, maxsplit=1)[0]
    return hostname.removeprefix("www.")[:_MAX_SITE_NAME_LENGTH]


def discover_site(raw_url: str) -> SiteDiscoveryResult:
    origin = normalize_site_origin(raw_url)
    deadline = time.monotonic() + _MAX_DISCOVERY_SECONDS
    budget = _RequestBudget(_MAX_DISCOVERY_REQUESTS)
    hostname = urlparse(origin).hostname or origin
    declared_sitemaps: list[str] = []
    og_site_name = ""
    title = ""

    try:
        robots = _fetch_text(f"{origin}/robots.txt", deadline=deadline, budget=budget)
        declared_sitemaps = _sitemaps_from_robots(robots.text, origin=origin)
    except PublicUrlFetchError:
        pass

    try:
        parser = _SiteNameParser()
        parser.feed(_fetch_text(f"{origin}/", deadline=deadline, budget=budget).text)
        og_site_name = parser.og_site_name
        title = parser.title
    except PublicUrlFetchError:
        pass

    detected_sitemaps = _verified_sitemaps(
        list(dict.fromkeys(declared_sitemaps))[:_MAX_SITEMAP_CANDIDATES], deadline=deadline, budget=budget
    ) or _verified_sitemaps(
        [f"{origin}{path}" for path in _CONVENTIONAL_SITEMAP_PATHS], deadline=deadline, budget=budget
    )

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
