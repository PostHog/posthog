import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.snyk.settings import (
    SNYK_ENDPOINTS,
    SnykEndpointConfig,
    SnykScope,
)

# Snyk regional stacks are independent and don't share data; the region selects which API host
# the token is sent to. The set is a fixed allow-list, so the host can't be retargeted.
SNYK_REGION_HOSTS = {
    "us": "https://api.snyk.io",
    "eu": "https://api.eu.snyk.io",
    "au": "https://api.au.snyk.io",
}
DEFAULT_REGION = "us"

# Every Snyk REST call requires a dated ``version`` query param; omitting it is an error.
# This is a GA version that includes the issues endpoint's ``updated_after``/``created_after``
# filters. Snyk keeps GA versions available through a long deprecation window.
SNYK_REST_VERSION = "2024-10-15"

REQUEST_TIMEOUT_SECONDS = 60

# Snyk org ids are UUIDs. The configured org id is interpolated into a URL path, so reject
# anything that could alter the path shape before it gets near a request.
_ORG_ID_RE = re.compile(r"^[a-zA-Z0-9-]+$")


class SnykRetryableError(Exception):
    pass


@dataclasses.dataclass
class SnykResumeConfig:
    # Next page URL (from the JSON:API ``links.next``) to fetch on resume.
    next_url: str
    # The fan-out org currently being processed. A stable id rather than a positional index so
    # orgs added/removed between a crash and the retry can't resume into the wrong one. None for
    # the top-level organizations endpoint.
    org_id: str | None = None


def base_url(region: Optional[str]) -> str:
    return SNYK_REGION_HOSTS.get(region or DEFAULT_REGION, SNYK_REGION_HOSTS[DEFAULT_REGION])


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"token {api_token}",
        "Accept": "application/vnd.api+json",
    }


def _build_url(host: str, path: str, params: dict[str, Any]) -> str:
    return f"{host}/rest{path}?{urlencode(params)}"


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as RFC 3339 with a ``Z`` suffix for Snyk filters."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        return str(value)
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_same_host(url: str, host: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc == urlparse(host).netloc


def _next_page_url(host: str, payload: Any) -> str | None:
    """Resolve the JSON:API ``links.next`` value into an absolute URL on the resolved host.

    Snyk returns ``links.next`` either as a string or a ``{"href": ...}`` object, and as a
    relative path that may or may not carry the ``/rest`` prefix depending on API version. Only
    same-host absolute URLs are followed, so a tampered response can't point our authenticated
    request at another server (SSRF) and leak the token header.
    """
    links = payload.get("links") if isinstance(payload, dict) else None
    next_link = links.get("next") if isinstance(links, dict) else None
    if isinstance(next_link, dict):
        next_link = next_link.get("href")
    if not isinstance(next_link, str) or not next_link:
        return None
    if next_link.startswith("http"):
        return next_link if _is_same_host(next_link, host) else None
    if not next_link.startswith("/"):
        next_link = f"/{next_link}"
    if not next_link.startswith("/rest/"):
        next_link = f"/rest{next_link}"
    return f"{host}{next_link}"


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Lift a JSON:API record's ``attributes`` object to the root, keeping ``id``/``type``."""
    attributes = item.get("attributes")
    if isinstance(attributes, dict):
        item.pop("attributes")
        for key, value in attributes.items():
            item.setdefault(key, value)
    return item


@retry(
    retry=retry_if_exception_type((SnykRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> Any:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    # Snyk rate limits per token and returns 429 (with Retry-After) on exceed; retry those plus
    # transient 5xx with exponential backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise SnykRetryableError(f"Snyk API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Snyk API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _fetch_list_page(
    session: requests.Session, url: str, host: str, logger: FilteringBoundLogger
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch one page of a Snyk REST list endpoint, returning (items, next_page_url)."""
    payload = _fetch_page(session, url, logger)
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return [], None
    return items, _next_page_url(host, payload)


def _validated_org_id(organization_id: str) -> str:
    org_id = organization_id.strip()
    if not _ORG_ID_RE.match(org_id):
        raise ValueError(f"Invalid Snyk organization id: {organization_id!r}")
    return org_id


def _resolve_org_ids(
    session: requests.Session, host: str, organization_id: Optional[str], logger: FilteringBoundLogger
) -> list[str]:
    """The org ids to fan out over: the configured single org, or every org the token can see."""
    if organization_id and organization_id.strip():
        return [_validated_org_id(organization_id)]

    org_ids: list[str] = []
    url: str | None = _build_url(host, "/orgs", {"version": SNYK_REST_VERSION, "limit": 100})
    while url:
        items, url = _fetch_list_page(session, url, host, logger)
        org_ids.extend(item["id"] for item in items)
    return org_ids


def _initial_params(
    config: SnykEndpointConfig,
    incremental_field: Optional[str],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"version": SNYK_REST_VERSION, "limit": config.page_size}

    # ``links.next`` carries all query params forward, so applying the watermark filter to the
    # first page keeps every subsequent page bounded too.
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        field = incremental_field or config.default_incremental_field
        filter_param = config.incremental_param_by_field.get(field) if field else None
        if filter_param:
            params[filter_param] = _format_datetime(db_incremental_field_last_value)

    return params


def _iter_single_org(
    session: requests.Session,
    host: str,
    organization_id: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Emit only the configured organization instead of every org the token can reach.

    ``GET /rest/orgs/{org_id}`` returns that one org as a single JSON:API object. Honoring the
    configured id here keeps a single-org connection scoped to that org, so a member can't
    enumerate every organization the token can see via the organizations table.
    """
    org_id = _validated_org_id(organization_id)
    url = _build_url(host, f"/orgs/{org_id}", {"version": SNYK_REST_VERSION})
    payload = _fetch_page(session, url, logger)
    item = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(item, dict):
        yield [_flatten_item(item)]


def _iter_top_level(
    session: requests.Session,
    host: str,
    config: SnykEndpointConfig,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[SnykResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Paginate a top-level collection (organizations) with resume support."""
    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None and resume.next_url:
        if not _is_same_host(resume.next_url, host):
            raise ValueError(f"Snyk resume state contains an unexpected URL: {resume.next_url!r}")
        url = resume.next_url
        logger.debug(f"Snyk: resuming {config.name} from URL: {url}")
    else:
        url = _build_url(host, config.path, params)

    while True:
        items, next_url = _fetch_list_page(session, url, host, logger)
        if items:
            yield [_flatten_item(item) for item in items]
        if not next_url:
            break
        # Save AFTER yielding the batch — a crash before the save re-yields this page (merge
        # dedupes on primary key) instead of skipping it.
        manager.save_state(SnykResumeConfig(next_url=next_url))
        url = next_url


def _iter_fan_out(
    session: requests.Session,
    host: str,
    config: SnykEndpointConfig,
    params: dict[str, Any],
    organization_id: Optional[str],
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[SnykResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk every org and emit each org's rows, injecting ``organization_id`` into each row."""
    org_ids = _resolve_org_ids(session, host, organization_id, logger)

    # Resolve the saved org bookmark to the slice of orgs still to process. If the bookmarked org
    # no longer exists (removed between runs), start over — merge dedupes the re-pulled rows.
    resume = manager.load_state() if manager.can_resume() else None
    start_index = 0
    resume_url: str | None = None
    if resume is not None and resume.org_id is not None and resume.org_id in org_ids:
        if not _is_same_host(resume.next_url, host):
            raise ValueError(f"Snyk resume state contains an unexpected URL: {resume.next_url!r}")
        start_index = org_ids.index(resume.org_id)
        resume_url = resume.next_url
        logger.debug(f"Snyk: resuming {config.name} fan-out from org={resume.org_id}, url={resume_url}")

    for index in range(start_index, len(org_ids)):
        org_id = org_ids[index]
        url = resume_url or _build_url(host, config.path.format(org_id=org_id), params)
        resume_url = None  # only the resumed-into org uses the saved URL; the rest start fresh

        while True:
            items, next_url = _fetch_list_page(session, url, host, logger)
            if items:
                yield [{**_flatten_item(item), "organization_id": org_id} for item in items]
            if not next_url:
                break
            manager.save_state(SnykResumeConfig(next_url=next_url, org_id=org_id))
            url = next_url


def get_rows(
    region: Optional[str],
    api_token: str,
    organization_id: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SnykResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SNYK_ENDPOINTS[endpoint]
    host = base_url(region)
    # One tracked session reused across every page (and every fan-out org) so urllib3 keeps the
    # connection alive. Redact the token: it rides in the ``Authorization: token …`` header under
    # Snyk's custom scheme, which the tracked transport's built-in scrubber doesn't recognise.
    session = make_tracked_session(headers=_get_headers(api_token), redact_values=(api_token,))

    params = _initial_params(config, incremental_field, should_use_incremental_field, db_incremental_field_last_value)

    if config.scope == SnykScope.ORGANIZATION:
        if organization_id and organization_id.strip():
            yield from _iter_single_org(session, host, organization_id, logger)
        else:
            yield from _iter_top_level(session, host, config, params, logger, resumable_source_manager)
    else:
        yield from _iter_fan_out(session, host, config, params, organization_id, logger, resumable_source_manager)


def snyk_source(
    region: Optional[str],
    api_token: str,
    organization_id: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SnykResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    endpoint_config = SNYK_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            region=region,
            api_token=api_token,
            organization_id=organization_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Snyk documents no sort param on these endpoints and the response order is undefined —
        # and the multi-org fan-out breaks any global ordering anyway. "desc" defers the watermark
        # write to sync completion (max value seen), which is the safe semantic for unordered data;
        # "asc" would checkpoint a max-so-far watermark mid-sync and could skip rows on retry.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(
    region: Optional[str], api_token: str, organization_id: Optional[str] = None
) -> tuple[bool, str | None]:
    """Confirm the token is genuine with a single cheap probe.

    ``/rest/self`` validates the token alone; when a single org is configured, probing that org
    also confirms the token can reach it on the selected region.
    """
    host = base_url(region)
    if organization_id and organization_id.strip():
        try:
            org_id = _validated_org_id(organization_id)
        except ValueError:
            return False, "Snyk organization ID is invalid — copy it from your organization settings."
        url = _build_url(host, f"/orgs/{org_id}", {"version": SNYK_REST_VERSION})
    else:
        url = _build_url(host, "/self", {"version": SNYK_REST_VERSION})

    try:
        session = make_tracked_session(redact_values=(api_token,))
        response = session.get(url, headers=_get_headers(api_token), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Snyk API token. Check the token and the selected region, then try again."
    if response.status_code in (403, 404):
        return False, "Your Snyk token can't access this organization. Check the organization ID and region."
    return False, f"Snyk API error: {response.status_code}"
