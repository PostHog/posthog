import time
import uuid
import hashlib
import ipaddress
import dataclasses
from collections.abc import Iterable
from io import BytesIO
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache

import structlog
from PIL import Image

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.models.uploaded_media import (
    MEDIA_PURPOSE_EMAIL,
    ObjectStorageUnavailable,
    UploadedMedia,
    sniff_image_content_type,
)
from posthog.security.url_validation import validate_url_and_pin_ips

from products.messaging.backend.services.website_brand import (
    BrandSignals,
    LogoCandidate,
    ManifestSignals,
    largest_first,
    read_brand_signals,
    read_manifest_signals,
)
from products.messaging.backend.services.website_fetch import (
    ByteLimit,
    FetchedResource,
    WebsiteFetchError,
    fetch_public_resource,
)

logger = structlog.get_logger(__name__)

_SETTLED_FRESH_SECONDS = 24 * 60 * 60
_UNSETTLED_FRESH_SECONDS = 15 * 60
_DETECTION_BUDGET_SECONDS = 15.0
_RUNNING_DETECTION_SECONDS = 40
_RUNNING_DETECTION_POLL_SECONDS = 0.25
_PAGE_HEAD_LIMIT = ByteLimit(max_bytes=1024 * 1024, keep_prefix=True)
_MANIFEST_LIMIT = ByteLimit(max_bytes=256 * 1024)
_LOGO_LIMIT = ByteLimit(max_bytes=4 * 1024 * 1024 - 1)
_MAX_LOGO_ATTEMPTS = 3
_MIN_LOGO_SIDE_PX = 128
_EMAIL_LOGO_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml", ""})
_PREVIEW_HOST_SUFFIXES = (
    ".vercel.app",
    ".netlify.app",
    ".pages.dev",
    ".herokuapp.com",
    ".ngrok.io",
    ".ngrok.app",
    ".ngrok-free.app",
    ".local",
    ".localhost",
    ".internal",
    ".test",
)
_TOP_PAGEVIEW_HOSTS_QUERY = """
    SELECT properties.$host AS host, count() AS pageviews
    FROM events
    WHERE event = '$pageview'
        AND timestamp >= now() - INTERVAL 3 DAY
        AND timestamp <= now()
        AND notEmpty(properties.$host)
    GROUP BY host
    ORDER BY pageviews DESC
    LIMIT 100
"""


@frozen
class DetectedBrand:
    website: str | None
    name: str | None
    primary_color: str | None
    logo_url: str | None


NOTHING_DETECTED = DetectedBrand(website=None, name=None, primary_color=None, logo_url=None)


@frozen
class _Detection:
    brand: DetectedBrand
    settled: bool


def detected_brand(team: Team, user: User) -> DetectedBrand:
    cache_key = f"messaging:detected_brand:{team.pk}"
    running_key = f"{cache_key}:running"
    if (fresh := _fresh_brand(cache_key)) is not None:
        return fresh
    run_token = uuid.uuid4().hex
    if not cache.add(running_key, run_token, _RUNNING_DETECTION_SECONDS):
        return _brand_of_running_detection(cache_key, running_key)
    try:
        if (fresh := _fresh_brand(cache_key)) is not None:
            return fresh
        detection = _detect_brand(team, user)
        _remember(cache_key, detection)
        return detection.brand
    finally:
        if cache.get(running_key) == run_token:
            cache.delete(running_key)


def _fresh_brand(cache_key: str) -> DetectedBrand | None:
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and cached.get("fresh_until", 0) > time.time():
        return DetectedBrand(**cached["brand"])
    return None


def _remember(cache_key: str, detection: "_Detection") -> None:
    fresh_seconds = _SETTLED_FRESH_SECONDS if detection.settled else _UNSETTLED_FRESH_SECONDS
    cache.set(
        cache_key,
        {"brand": dataclasses.asdict(detection.brand), "fresh_until": time.time() + fresh_seconds},
        _SETTLED_FRESH_SECONDS,
    )


def _brand_of_running_detection(cache_key: str, running_key: str) -> DetectedBrand:
    give_up_at = time.monotonic() + _RUNNING_DETECTION_SECONDS
    while time.monotonic() < give_up_at and cache.get(running_key):
        time.sleep(_RUNNING_DETECTION_POLL_SECONDS)
    return _fresh_brand(cache_key) or NOTHING_DETECTED


def public_host(raw: str) -> str | None:
    value = raw.strip()
    try:
        host = urlparse(value if "://" in value else f"//{value}").hostname
    except ValueError:
        return None
    host = (host or "").lower().removesuffix(".")
    if "." not in host or "*" in host or host.endswith(_PREVIEW_HOST_SUFFIXES) or _is_ip_literal(host):
        return None
    return host


def _detect_brand(team: Team, user: User) -> _Detection:
    deadline = time.monotonic() + _DETECTION_BUDGET_SECONDS
    try:
        host = _team_website_host(team, deadline)
    except WebsiteFetchError:
        return _Detection(brand=NOTHING_DETECTED, settled=False)
    except Exception as error:
        capture_exception(error)
        return _Detection(brand=NOTHING_DETECTED, settled=False)
    if host is None:
        return _Detection(brand=NOTHING_DETECTED, settled=True)
    website = f"https://{host}/"
    try:
        signals = _read_website(website, deadline)
    except WebsiteFetchError as error:
        logger.info("messaging.brand_detection.website_unreachable", reason=str(error))
        return _Detection(brand=dataclasses.replace(NOTHING_DETECTED, website=website), settled=False)
    if signals is None:
        return _Detection(brand=dataclasses.replace(NOTHING_DETECTED, website=website), settled=True)
    manifest = _read_manifest(signals.manifest_url, deadline)
    brand = DetectedBrand(
        website=website,
        name=signals.name,
        primary_color=signals.theme_color or manifest.theme_color or signals.tile_color,
        logo_url=_hosted_logo_url(largest_first(signals.logos + manifest.logos), team, user, deadline),
    )
    return _Detection(brand=brand, settled=True)


def _team_website_host(team: Team, deadline: float) -> str | None:
    authorized_hosts = (public_host(app_url) for app_url in team.app_urls or [] if app_url)
    if host := _first_reachable(authorized_hosts, deadline):
        return host
    return _first_reachable((public_host(top_host) for top_host in _top_pageview_hosts(team)), deadline)


def _first_reachable(hosts: Iterable[str | None], deadline: float) -> str | None:
    for host in hosts:
        if time.monotonic() >= deadline:
            raise WebsiteFetchError("deadline")
        if host and validate_url_and_pin_ips(f"https://{host}/").allowed:
            return host
    return None


def _top_pageview_hosts(team: Team) -> list[str]:
    with tags_context(product=Product.WORKFLOWS, feature=Feature.ENRICHMENT):
        response = execute_hogql_query(
            _TOP_PAGEVIEW_HOSTS_QUERY,
            team=team,
            query_type="messaging_brand_website_hosts",
            settings=HogQLGlobalSettings(max_execution_time=10),
        )
    return [str(row[0]) for row in response.results or []]


def _read_website(website: str, deadline: float) -> BrandSignals | None:
    page = fetch_public_resource(
        website, accept="text/html,application/xhtml+xml", limit=_PAGE_HEAD_LIMIT, deadline=deadline
    )
    if page.content_type not in _HTML_TYPES:
        return None
    return read_brand_signals(page.text(), page.url)


def _read_manifest(manifest_url: str | None, deadline: float) -> ManifestSignals:
    if manifest_url is None:
        return ManifestSignals(theme_color=None, logos=())
    try:
        manifest = fetch_public_resource(
            manifest_url,
            accept="application/manifest+json,application/json",
            limit=_MANIFEST_LIMIT,
            deadline=deadline,
        )
    except WebsiteFetchError:
        return ManifestSignals(theme_color=None, logos=())
    return read_manifest_signals(manifest.text(), manifest.url)


def _hosted_logo_url(candidates: tuple[LogoCandidate, ...], team: Team, user: User, deadline: float) -> str | None:
    for candidate in candidates[:_MAX_LOGO_ATTEMPTS]:
        try:
            image = fetch_public_resource(candidate.url, accept="image/*", limit=_LOGO_LIMIT, deadline=deadline)
        except WebsiteFetchError:
            continue
        content_type = _email_logo_type(image)
        if content_type is not None:
            return _store_logo(image.body, content_type, team, user)
    return None


def _email_logo_type(image: FetchedResource) -> str | None:
    content_type = sniff_image_content_type(image.body)
    if content_type not in _EMAIL_LOGO_EXTENSIONS:
        return None
    with Image.open(BytesIO(image.body)) as decoded:
        return content_type if max(decoded.size) >= _MIN_LOGO_SIDE_PX else None


def _store_logo(body: bytes, content_type: str, team: Team, user: User) -> str | None:
    if not settings.OBJECT_STORAGE_ENABLED:
        return None
    file_name = f"website-logo-{hashlib.sha256(body).hexdigest()[:16]}.{_EMAIL_LOGO_EXTENSIONS[content_type]}"
    stored = UploadedMedia.objects.filter(
        team=team, purpose=MEDIA_PURPOSE_EMAIL, file_name=file_name, pending=False, media_location__isnull=False
    ).first()
    if stored is None:
        stored = _save_logo(body, content_type, file_name, team, user)
    return stored.get_absolute_url() if stored else None


def _save_logo(body: bytes, content_type: str, file_name: str, team: Team, user: User) -> UploadedMedia | None:
    try:
        media = UploadedMedia.save_content(
            team=team,
            created_by=user,
            file_name=file_name,
            content_type=content_type,
            content=body,
            purpose=MEDIA_PURPOSE_EMAIL,
        )
    except ObjectStorageUnavailable:
        return None
    if media is not None:
        media.size_bytes = len(body)
        media.save(update_fields=["size_bytes"])
    return media


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True
