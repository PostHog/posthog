import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.unleash.settings import (
    UNLEASH_ENDPOINTS,
    UnleashEndpointConfig,
)

# The feature search endpoint documents a default limit of 50; 100 verified working against a
# live instance and keeps round trips low.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap list endpoint used to confirm the token is genuine. Every admin-capable token (personal
# access token, service account token) can read projects.
DEFAULT_PROBE_PATH = "/api/admin/projects"

HOST_NOT_ALLOWED_ERROR = "Unleash instance URL is not allowed"


class UnleashRetryableError(Exception):
    pass


class UnleashHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class UnleashResumeConfig:
    # Offset of the next feature-search page to fetch. Only the features endpoint paginates;
    # a crashed sync resumes from the page after the last one yielded and merge dedupes the
    # re-pulled page on the primary key. The other endpoints return the whole collection in one
    # request, so there is nothing to resume.
    offset: int = 0


def normalize_instance_url(instance_url: str) -> str:
    """Turn whatever the user typed into a consistent instance base URL.

    Unleash instances live at a per-customer URL that may include a path prefix (e.g.
    ``https://us.app.unleash-hosted.com/some-instance`` on Unleash cloud), so the path must be
    preserved — we only strip a scheme-less prefix, trailing slashes, and an accidentally-pasted
    ``/api`` or ``/api/admin`` suffix.
    """
    url = instance_url.strip().rstrip("/")
    if url and not re.match(r"^https?://", url, flags=re.IGNORECASE):
        url = f"https://{url}"
    for suffix in ("/api/admin", "/api"):
        if url.lower().endswith(suffix):
            url = url[: -len(suffix)]
            break
    return url.rstrip("/")


def _headers(api_token: str) -> dict[str, str]:
    # Unleash expects the token as the raw Authorization header value — no Bearer prefix
    # (verified against a live instance; a Bearer-prefixed token is rejected).
    return {"Authorization": api_token, "Accept": "application/json"}


def _check_host(instance_url: str, team_id: int) -> None:
    hostname = urlparse(normalize_instance_url(instance_url)).hostname
    if not hostname:
        raise UnleashHostNotAllowedError(HOST_NOT_ALLOWED_ERROR)
    host_ok, host_err = _is_host_safe(hostname, team_id)
    if not host_ok:
        raise UnleashHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)


def _extract_rows(data: Any, config: UnleashEndpointConfig, url: str) -> list[dict[str, Any]]:
    if config.data_selector is None:
        if not isinstance(data, list):
            raise UnleashRetryableError(f"Unleash returned an unexpected payload for {url}: {type(data).__name__}")
        return data
    if not isinstance(data, dict) or not isinstance(data.get(config.data_selector), list):
        raise UnleashRetryableError(f"Unleash returned an unexpected payload for {url}: {type(data).__name__}")
    return data[config.data_selector]


@retry(
    retry=retry_if_exception_type((UnleashRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    url: str,
    params: Optional[dict[str, Any]],
    logger: FilteringBoundLogger,
) -> Any:
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise UnleashRetryableError(f"Unleash API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Unleash API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    instance_url: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UnleashResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = UNLEASH_ENDPOINTS[endpoint]
    # Re-check at run time (not just at source-create) in case the instance URL was edited or now
    # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    _check_host(instance_url, team_id)

    base_url = normalize_instance_url(instance_url)
    url = f"{base_url}{config.path}"
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))

    if not config.paginated:
        rows = _extract_rows(_fetch(session, url, None, logger), config, url)
        if rows:
            yield rows
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume else 0
    if resume:
        logger.debug(f"Unleash: resuming {endpoint} from offset {offset}")

    while True:
        # Sort by createdAt ascending so page boundaries stay stable while we walk the offsets —
        # flags created mid-sync land at the end instead of shifting earlier pages.
        params: dict[str, Any] = {
            "limit": PAGE_SIZE,
            "offset": offset,
            "sortBy": "createdAt",
            "sortOrder": "asc",
        }
        data = _fetch(session, url, params, logger)
        rows = _extract_rows(data, config, url)
        if rows:
            yield rows

        offset += len(rows)
        total = data.get("total") if isinstance(data, dict) else None
        # Stop on a short/empty page, or once the reported total is reached.
        if len(rows) < PAGE_SIZE or (isinstance(total, int) and offset >= total):
            break

        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(UnleashResumeConfig(offset=offset))


def unleash_source(
    instance_url: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UnleashResumeConfig],
) -> SourceResponse:
    config = UNLEASH_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            instance_url=instance_url,
            api_token=api_token,
            endpoint=endpoint,
            team_id=team_id,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def _error_message(response: requests.Response) -> Optional[str]:
    # Unleash error bodies carry a human-readable `message` (e.g. PermissionError details).
    try:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("message"), str):
            return body["message"]
    except Exception:
        pass
    return None


def validate_credentials(
    instance_url: str, api_token: str, schema_name: Optional[str] = None, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe a cheap list endpoint to confirm the token is genuine.

    At source-create (``schema_name is None``) a 403 is accepted: the token is valid but may lack
    the permission for this particular probe. A scoped probe (``schema_name`` set) treats 403 as a
    hard failure.
    """
    base_url = normalize_instance_url(instance_url)
    hostname = urlparse(base_url).hostname
    if not hostname:
        return False, "Invalid Unleash instance URL"

    # The instance URL is fully customer-controlled, so block hosts that resolve to private/
    # internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(hostname, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))
    try:
        # Don't follow redirects: the validated host could 3xx to an internal address, defeating
        # the host check above (SSRF).
        response = session.get(f"{base_url}{DEFAULT_PROBE_PATH}", timeout=15, allow_redirects=False)
    except requests.exceptions.RequestException as e:
        return False, f"Could not connect to Unleash: {e}"

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid Unleash API token"

    if response.status_code == 403:
        if schema_name is None:
            # Valid token, missing permission for this probe — let source creation through.
            return True, None
        return False, _error_message(response) or "Your Unleash API token lacks the required permissions"

    return False, _error_message(response) or f"Unleash returned HTTP {response.status_code}"


def check_endpoint_permissions(
    instance_url: str, api_token: str, endpoints: list[str], team_id: int
) -> dict[str, str | None]:
    """Probe each endpoint and report which ones the token cannot read.

    Returns ``{endpoint: None}`` when reachable and ``{endpoint: reason}`` on a real denial
    (401/403). Transient failures (throttles, 5xx, network blips) are not permission problems, so
    they report as reachable rather than blocking the schema picker.
    """
    base_url = normalize_instance_url(instance_url)
    hostname = urlparse(base_url).hostname
    if not hostname:
        return dict.fromkeys(endpoints, "Invalid Unleash instance URL")
    host_ok, host_err = _is_host_safe(hostname, team_id)
    if not host_ok:
        return dict.fromkeys(endpoints, host_err or HOST_NOT_ALLOWED_ERROR)

    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))
    results: dict[str, str | None] = {}
    for endpoint in endpoints:
        config = UNLEASH_ENDPOINTS.get(endpoint)
        if config is None:
            results[endpoint] = None
            continue
        params = {"limit": 1} if config.paginated else None
        try:
            response = session.get(f"{base_url}{config.path}", params=params, timeout=15, allow_redirects=False)
        except requests.exceptions.RequestException:
            results[endpoint] = None
            continue
        if response.status_code == 401:
            results[endpoint] = "Invalid Unleash API token"
        elif response.status_code == 403:
            reason = _error_message(response) or "Your Unleash API token lacks the required permissions"
            if config.requires_admin:
                reason = f"{reason} This table requires a token with the Admin root role."
            results[endpoint] = reason
        else:
            results[endpoint] = None
    return results
