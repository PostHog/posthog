from collections.abc import Iterator
from typing import Any
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.settings import (
    FLY_IO_ENDPOINTS,
    FlyIoEndpointConfig,
)

FLY_IO_BASE_URL = "https://api.machines.dev/v1"

# Advisory page size for the cursor-paginated org endpoints (the API caps it at 1000).
_PAGE_SIZE = 1000

# Hard cap on pages walked per stream so a misbehaving cursor can't loop forever.
_MAX_PAGES = 1000

# A Fly machine's `config` can embed deployment secrets, so we sync only an operational
# allowlist (the "overview" the canonical description promises) rather than the raw object.
# Anything not listed here — notably `env`, `files` (whose entries carry inline file
# contents in `raw_value`), and `secrets` — is dropped before the row reaches the warehouse.
_SAFE_MACHINE_CONFIG_KEYS = frozenset(
    {
        "guest",
        "image",
        "metadata",
        "services",
        "checks",
        "restart",
        "mounts",
        "metrics",
        "init",
        "processes",
        "auto_destroy",
        "schedule",
        "dns",
        "size",
        "standbys",
        "statics",
        "stop_config",
    }
)

# A machine's per-process config entries repeat the same secret vectors as the top level.
_PROCESS_SECRET_KEYS = frozenset({"env", "secrets"})

# `metadata` is a free-form user key/value map, so a value like `metadata.api_token` would
# otherwise reach the warehouse. Only Fly's own platform-set keys are known-safe; everything
# else is dropped.
_SAFE_METADATA_KEYS = frozenset(
    {
        "fly_platform_version",
        "fly_process_group",
        "fly_release_id",
        "fly_release_version",
        "fly_flyctl_version",
        "fly_managed_postgres",
    }
)


class FlyIoRetryableError(Exception):
    pass


def _strip_headers(value: Any) -> Any:
    """Recursively drop every `headers` mapping from a nested structure. Fly service and check
    definitions can carry request headers (e.g. a health-check `Authorization`), a credential
    vector we never want to land in the warehouse."""
    if isinstance(value, dict):
        return {key: _strip_headers(item) for key, item in value.items() if key != "headers"}
    if isinstance(value, list):
        return [_strip_headers(item) for item in value]
    return value


def _sanitize_machine_config(config: dict[str, Any]) -> dict[str, Any]:
    safe = {key: value for key, value in config.items() if key in _SAFE_MACHINE_CONFIG_KEYS}
    # `metadata` is user-defined free-form key/values; keep only Fly's own platform keys so a
    # user-set secret (e.g. `metadata.api_token`) can't slip through the allowlist.
    metadata = safe.get("metadata")
    if isinstance(metadata, dict):
        safe["metadata"] = {key: value for key, value in metadata.items() if key in _SAFE_METADATA_KEYS}
    # `processes` is operational (cmd/entrypoint/guest) but each entry can carry its own
    # `env`/`secrets`, so strip those while keeping the rest of the process definition.
    processes = safe.get("processes")
    if isinstance(processes, list):
        safe["processes"] = [
            {key: value for key, value in process.items() if key not in _PROCESS_SECRET_KEYS}
            if isinstance(process, dict)
            else process
            for process in processes
        ]
    # Final defensive pass: `services`/`checks` (and anything nested under them) can embed
    # request-header maps that carry credentials — drop them wherever they appear.
    return _strip_headers(safe)


def _sanitize_machine(row: dict[str, Any]) -> dict[str, Any]:
    config = row.get("config")
    if isinstance(config, dict):
        return {**row, "config": _sanitize_machine_config(config)}
    return row


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _build_url(config: FlyIoEndpointConfig, org_slug: str, params: dict[str, Any]) -> str:
    """Build the request URL for an endpoint. Org-scoped endpoints carry the org in the path;
    the apps endpoint takes it as a required query param instead."""
    if "{org_slug}" in config.path:
        # Encode the slug so a reserved character (e.g. `/`) can't retarget the request to a
        # different API path than the one credential validation checked.
        path = config.path.format(org_slug=quote(org_slug, safe=""))
        query = dict(params)
    else:
        path = config.path
        query = {"org_slug": org_slug, **params}
    url = f"{FLY_IO_BASE_URL}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    return url


@retry(
    # ChunkedEncodingError is a mid-stream connection break (a truncated chunked body); it's
    # transient like ConnectionError/ReadTimeout but not a ConnectionError subclass.
    retry=retry_if_exception_type(
        (
            FlyIoRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    # 429 (rate limited) and 5xx are transient — retry with backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise FlyIoRetryableError(f"Fly.io API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Fly.io API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    # Every list endpoint we sync wraps its rows in an object ({"apps": [...]} etc.). A bare list
    # or scalar is an unexpected shape: fail loudly rather than silently syncing zero rows, which
    # would look like a successful-but-empty sync if Fly.io ever changed the wrapper.
    if not isinstance(data, dict):
        raise ValueError(f"Fly.io API returned an unexpected response shape: {type(data).__name__}")
    return data


def validate_credentials(api_token: str, org_slug: str) -> tuple[bool, str | None]:
    """Probe the apps endpoint to confirm the token is genuine and the org is reachable."""
    url = _build_url(FLY_IO_ENDPOINTS["apps"], org_slug, {})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_token), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Fly.io API token. Create a new token with `fly tokens create org` and reconnect."
    if response.status_code in (403, 404):
        return False, f"Organization '{org_slug}' was not found or is not accessible with this token."

    try:
        message = response.json().get("error", response.text)
    except ValueError:
        message = response.text
    return False, message


def get_rows(
    api_token: str,
    endpoint: str,
    org_slug: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Yield one page of rows at a time. The org machines/volumes endpoints paginate with an
    opaque `next_cursor`; the apps endpoint returns everything in a single response. Rows are
    yielded in the shape the API returns them (flat objects, with nested config/organization kept
    as-is) — the pipeline batches and writes them."""
    config = FLY_IO_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    # One session reused across pages so urllib3 keeps the connection alive between requests.
    # A stream whose bodies can carry secrets opts out of HTTP sample capture (still logged
    # and metered) so those secrets never land in the sample-capture pipeline.
    session = make_tracked_session(capture=not config.redact_secrets)

    params: dict[str, Any] = {"limit": _PAGE_SIZE} if config.paginated else {}
    url = _build_url(config, org_slug, params)

    pages = 0
    while True:
        data = _fetch_page(session, url, headers, logger)

        items = data.get(config.response_data_path) or []
        if config.redact_secrets:
            items = [_sanitize_machine(item) for item in items]
        if items:
            yield items

        if not config.paginated:
            break

        next_cursor = data.get("next_cursor")
        if not next_cursor:
            break

        pages += 1
        if pages >= _MAX_PAGES:
            logger.warning(
                "Fly.io: pagination cap reached; remaining pages skipped",
                endpoint=endpoint,
                max_pages=_MAX_PAGES,
            )
            break

        url = _build_url(config, org_slug, {**params, "cursor": next_cursor})


def fly_io_source(
    api_token: str,
    endpoint: str,
    org_slug: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = FLY_IO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_token=api_token, endpoint=endpoint, org_slug=org_slug, logger=logger),
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
