import re
from urllib.parse import urljoin, urlparse

import requests
import structlog
from bs4 import BeautifulSoup

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.integration import Integration
from posthog.models.organization_domain import OrganizationDomain
from posthog.security.pinned_requests import SSRFBlockedError, pinned_session

logger = structlog.get_logger(__name__)

_MAX_HTML_BYTES = 512 * 1024
_TIMEOUT_SECONDS = (3.0, 5.0)
_MAX_REDIRECTS = 2
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_TITLE_SEPARATORS = re.compile(r"\s+[|\-–·:]\s+")


@frozen
class BrandKit:
    domain: str
    site_name: str
    primary_color: str | None
    logo_url: str | None


def resolve_brand_domain(team: Team) -> str | None:
    """The domain the team sends email from is the brand its emails go out as, so it wins over the
    organization's verified login domains."""
    for integration in Integration.objects.filter(team_id=team.id, kind="email").order_by("created_at"):
        config = integration.config or {}
        domain = config.get("domain")
        if isinstance(domain, str) and domain and config.get("verified") is True:
            return domain.lower()
    verified = OrganizationDomain.objects.verified_domains().filter(organization_id=team.organization_id).first()
    return verified.domain.lower() if verified else None


def fetch_brand_kit(domain: str) -> BrandKit | None:
    html = _fetch_homepage(domain)
    if html is None:
        return None
    return parse_brand_kit(domain=domain, html=html, base_url=f"https://{domain}/")


def parse_brand_kit(*, domain: str, html: str, base_url: str) -> BrandKit:
    soup = BeautifulSoup(html, "html.parser")
    return BrandKit(
        domain=domain,
        site_name=_site_name(soup) or domain,
        primary_color=_theme_color(soup),
        logo_url=_logo_url(soup, base_url),
    )


def _site_name(soup: BeautifulSoup) -> str | None:
    og_site_name = soup.find("meta", attrs={"property": "og:site_name"})
    content = og_site_name.get("content") if og_site_name else None
    if isinstance(content, str) and content.strip():
        return content.strip()[:60]
    if soup.title and soup.title.string:
        # "Acme | Ship faster" names the site in its first part.
        return _TITLE_SEPARATORS.split(soup.title.string.strip())[0][:60] or None
    return None


def _theme_color(soup: BeautifulSoup) -> str | None:
    for name in ("theme-color", "msapplication-TileColor"):
        tag = soup.find("meta", attrs={"name": name})
        content = tag.get("content") if tag else None
        if isinstance(content, str) and _HEX_COLOR.match(content.strip()):
            return content.strip().lower()
    return None


def _logo_url(soup: BeautifulSoup, base_url: str) -> str | None:
    # A touch icon is square and sized for display, which suits an email header better than a favicon.
    for rel in ("apple-touch-icon", "icon"):
        for link in soup.find_all("link", href=True):
            rels = link.get("rel") or []
            if rel in [value.lower() for value in rels]:
                url = urljoin(base_url, str(link["href"]))
                if urlparse(url).scheme == "https":
                    return url
    return None


def _fetch_homepage(domain: str) -> str | None:
    url = f"https://{domain}/"
    for _ in range(_MAX_REDIRECTS + 1):
        try:
            with pinned_session(url) as session:
                response = session.get(
                    url,
                    timeout=_TIMEOUT_SECONDS,
                    allow_redirects=False,
                    stream=True,
                    headers={"Accept": "text/html", "Accept-Encoding": "identity"},
                )
                if response.is_redirect:
                    location = urljoin(url, response.headers.get("Location", ""))
                    if not _same_site(location, domain):
                        return None
                    url = location
                    continue
                if response.status_code != 200 or "html" not in response.headers.get("Content-Type", ""):
                    return None
                body = response.raw.read(_MAX_HTML_BYTES, decode_content=False)
                return body.decode(response.encoding or "utf-8", errors="replace")
        except (SSRFBlockedError, requests.RequestException):
            logger.info("workflows.data_suggestions.brand_fetch_failed", domain=domain)
            return None
    return None


def _same_site(url: str, domain: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == domain or host.endswith(f".{domain}"))
