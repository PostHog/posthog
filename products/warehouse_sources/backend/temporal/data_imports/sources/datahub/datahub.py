import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.datahub.settings import (
    DATAHUB_ENDPOINTS,
    DatahubEndpointConfig,
)

# The OpenAPI v3 scroll endpoints default to 10 entities per page; 100 keeps round trips low
# while staying far under any Elasticsearch result-window concern (scroll doesn't use windows).
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap probe used to confirm the token is genuine: dataPlatform is a small built-in collection
# (~60 rows) present on every DataHub instance.
DEFAULT_PROBE_ENTITY = "dataPlatform"

HOST_NOT_ALLOWED_ERROR = "DataHub instance URL is not allowed"


class DatahubRetryableError(Exception):
    pass


class DatahubHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class DatahubResumeConfig:
    # Opaque scroll cursor returned by the OpenAPI v3 entity endpoint; passing it back fetches
    # the next page. None means "start from the first page".
    scroll_id: str | None = None


def normalize_instance_url(instance_url: str) -> str:
    """Turn whatever the user typed into a consistent API base URL.

    DataHub instances live at a per-customer URL that may include a path prefix (DataHub Cloud
    serves the metadata service under ``https://<tenant>.acryl.io/gms``), so the path must be
    preserved — we only default a missing scheme, strip trailing slashes, and drop an
    accidentally-pasted ``/openapi`` suffix.
    """
    url = instance_url.strip().rstrip("/")
    # Only default the scheme for bare hosts — a non-http(s) scheme must survive normalization
    # so _validated_hostname can reject it.
    if url and "://" not in url:
        url = f"https://{url}"
    if url.lower().endswith("/openapi"):
        url = url[: -len("/openapi")]
    return url.rstrip("/")


def _headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}


def _get_session(api_token: str) -> requests.Session:
    # The instance URL is user-supplied, so pin redirects off so host validation and the
    # outbound request stay on the same target (SSRF defense-in-depth). Redact the token
    # from logs.
    return make_tracked_session(headers=_headers(api_token), redact_values=(api_token,), allow_redirects=False)


def _validated_hostname(base_url: str) -> Optional[str]:
    """Hostname of the normalized instance URL, or None when the URL is malformed or ambiguous.

    SSRF guard: urlparse treats a backslash as ordinary userinfo and an "@" as a userinfo
    separator, but urllib3/requests treat the backslash as an authority separator, so
    `https://127.0.0.1\\@example.com` validates as example.com yet connects to 127.0.0.1.
    A legitimate instance URL has no userinfo, so reject either construct outright (same
    guard as the Unleash source) and require a plain http(s) URL with a clean hostname.
    """
    if "\\" in base_url or "%5c" in base_url.lower():
        return None
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or "@" in parsed.netloc:
        return None
    # The PAT rides in the Authorization header on every request, so plaintext http would leak
    # it to any network observer. On PostHog Cloud the request egresses over the public
    # internet, so require https. Self-hosted operators control their own network path (e.g. a
    # GMS reachable only over http), so http stays allowed there — mirroring how host IP safety
    # is only enforced on cloud.
    if parsed.scheme == "http" and is_cloud():
        return None
    hostname = parsed.hostname
    if not hostname or not re.match(r"^[A-Za-z0-9.\-]+$", hostname):
        return None
    return hostname


def _check_host(instance_url: str, team_id: int) -> None:
    hostname = _validated_hostname(normalize_instance_url(instance_url))
    if not hostname:
        raise DatahubHostNotAllowedError(HOST_NOT_ALLOWED_ERROR)
    host_ok, host_err = _is_host_safe(hostname, team_id)
    if not host_ok:
        raise DatahubHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)


def _entity_url(base_url: str, entity_type: str) -> str:
    return f"{base_url}/openapi/v3/entity/{entity_type}"


def _scroll_params(scroll_id: str | None, count: int = PAGE_SIZE) -> dict[str, Any]:
    # Sort by urn ascending so page boundaries stay stable while scrolling — entities ingested
    # mid-sync can't shuffle already-walked pages.
    params: dict[str, Any] = {
        "query": "*",
        "count": count,
        "sortCriteria": "urn",
        "sortOrder": "ASCENDING",
    }
    if scroll_id:
        params["scrollId"] = scroll_id
    return params


def _extract_entities(data: Any, url: str) -> tuple[list[dict[str, Any]], str | None]:
    """Pull the entity rows and next-page cursor out of a scroll response.

    The scroll envelope is ``{"scrollId": "...", "entities": [...]}``; the final page omits
    ``scrollId``. A missing ``entities`` key on a dict payload is treated as an empty result.
    """
    if not isinstance(data, dict):
        raise DatahubRetryableError(f"DataHub returned an unexpected payload for {url}: {type(data).__name__}")
    entities = data.get("entities") or []
    if not isinstance(entities, list):
        raise DatahubRetryableError(f"DataHub returned an unexpected 'entities' payload for {url}")
    scroll_id = data.get("scrollId")
    return entities, scroll_id if isinstance(scroll_id, str) and scroll_id else None


@retry(
    retry=retry_if_exception_type((DatahubRetryableError, requests.ReadTimeout, requests.ConnectionError)),
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

    # The session never follows redirects: a 3xx would move the sync off the validated host
    # (SSRF), so refuse it rather than silently fetching an empty body.
    if 300 <= response.status_code < 400:
        raise DatahubHostNotAllowedError(HOST_NOT_ALLOWED_ERROR)

    if response.status_code == 429 or response.status_code >= 500:
        raise DatahubRetryableError(f"DataHub API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"DataHub API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    instance_url: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DatahubResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = DATAHUB_ENDPOINTS[endpoint]
    # Re-check at run time (not just at source-create) in case the instance URL was edited or now
    # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    _check_host(instance_url, team_id)

    base_url = normalize_instance_url(instance_url)
    url = _entity_url(base_url, config.entity_type)
    session = _get_session(api_token)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    scroll_id = resume.scroll_id if resume else None
    resuming = scroll_id is not None
    if resuming:
        logger.debug(f"DataHub: resuming {endpoint} from saved scroll cursor")

    while True:
        try:
            data = _fetch(session, url, _scroll_params(scroll_id), logger)
        except requests.HTTPError as exc:
            # A saved scroll cursor can go stale between attempts (scroll contexts are
            # server-side and expire). If the resumed first request is rejected, restart the
            # sweep from scratch — merge dedupes the re-pulled rows on the primary key.
            status = exc.response.status_code if exc.response is not None else None
            if resuming and status in (400, 404, 410):
                logger.warning(f"DataHub: saved scroll cursor for {endpoint} was rejected, restarting from scratch")
                resumable_source_manager.clear_state()
                scroll_id = None
                resuming = False
                continue
            raise
        resuming = False

        entities, next_scroll_id = _extract_entities(data, url)
        if entities:
            yield entities

        # No cursor (or an empty page, guarding against a server that echoes a cursor forever)
        # means the sweep is complete.
        if not next_scroll_id or not entities:
            break

        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages
        # are persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(DatahubResumeConfig(scroll_id=next_scroll_id))
        scroll_id = next_scroll_id


def datahub_source(
    instance_url: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DatahubResumeConfig],
) -> SourceResponse:
    config: DatahubEndpointConfig = DATAHUB_ENDPOINTS[endpoint]

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
    # DataHub error bodies (when present — 401s are empty) carry a human-readable `message`.
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
    """Probe a cheap entity list to confirm the token is genuine.

    At source-create (``schema_name is None``) a 403 is accepted: the token is valid but its
    owner may lack the view privilege for this particular entity type. A scoped probe
    (``schema_name`` set) treats 403 as a hard failure.
    """
    base_url = normalize_instance_url(instance_url)
    hostname = _validated_hostname(base_url)
    if not hostname:
        return False, "Invalid DataHub instance URL"

    # The instance URL is fully customer-controlled, so block hosts that resolve to private/
    # internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(hostname, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    probe_entity = DEFAULT_PROBE_ENTITY
    if schema_name is not None and schema_name in DATAHUB_ENDPOINTS:
        probe_entity = DATAHUB_ENDPOINTS[schema_name].entity_type

    session = _get_session(api_token)
    try:
        # The session never follows redirects: the validated host could 3xx to an internal
        # address, defeating the host check above (SSRF).
        response = session.get(_entity_url(base_url, probe_entity), params=_scroll_params(None, count=1), timeout=15)
    except requests.exceptions.RequestException as e:
        return False, f"Could not connect to DataHub: {e}"

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return (
            False,
            "Invalid DataHub access token. Check that Metadata Service Authentication is enabled on your instance and generate a new personal access token.",
        )

    if response.status_code == 403:
        if schema_name is None:
            # Valid token, missing view privilege for this probe — let source creation through.
            return True, None
        return False, _error_message(response) or "Your DataHub access token lacks the required view privileges"

    return False, _error_message(response) or f"DataHub returned HTTP {response.status_code}"


def check_endpoint_permissions(
    instance_url: str, api_token: str, endpoints: list[str], team_id: int
) -> dict[str, str | None]:
    """Probe each entity endpoint and report which ones the token cannot read.

    Returns ``{endpoint: None}`` when reachable and ``{endpoint: reason}`` on a real denial
    (401/403). Transient failures (throttles, 5xx, network blips) are not permission problems,
    so they report as reachable rather than blocking the schema picker.
    """
    base_url = normalize_instance_url(instance_url)
    hostname = _validated_hostname(base_url)
    if not hostname:
        return dict.fromkeys(endpoints, "Invalid DataHub instance URL")
    host_ok, host_err = _is_host_safe(hostname, team_id)
    if not host_ok:
        return dict.fromkeys(endpoints, host_err or HOST_NOT_ALLOWED_ERROR)

    session = _get_session(api_token)
    results: dict[str, str | None] = {}
    for endpoint in endpoints:
        config = DATAHUB_ENDPOINTS.get(endpoint)
        if config is None:
            results[endpoint] = None
            continue
        try:
            response = session.get(
                _entity_url(base_url, config.entity_type), params=_scroll_params(None, count=1), timeout=15
            )
        except requests.exceptions.RequestException:
            results[endpoint] = None
            continue
        if response.status_code == 401:
            results[endpoint] = "Invalid DataHub access token"
        elif response.status_code == 403:
            results[endpoint] = (
                _error_message(response) or "Your DataHub access token lacks the view privilege for this entity type"
            )
        else:
            results[endpoint] = None
    return results
