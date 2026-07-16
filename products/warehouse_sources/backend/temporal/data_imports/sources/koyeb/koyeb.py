import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.settings import (
    KOYEB_ENDPOINTS,
    KoyebEndpointConfig,
)

KOYEB_BASE_URL = "https://app.koyeb.com"

# Koyeb caps list page sizes at 100 (default 10); request the max to minimize round-trips.
PAGE_SIZE = 100

# Backstop against an endpoint that ignores `offset` (which would otherwise re-serve page one
# forever). Resumable state means an interrupted sync picks back up, so this is a runaway guard,
# not a coverage limit — at 100 rows/page it allows ~1M rows before warning.
MAX_PAGES = 10_000

# /v1/usages/details requires a time window; Koyeb launched in 2019, so this floor covers any
# organization's full usage history.
USAGE_WINDOW_START = "2019-01-01T00:00:00Z"


class KoyebRetryableError(Exception):
    pass


@dataclasses.dataclass
class KoyebResumeConfig:
    # The `offset` of the next page to fetch. Rows are requested in ascending order (where the
    # endpoint supports `order`), so rows appended mid-sync land after the offset and can't shift
    # earlier pages underneath it.
    offset: int = 0


# Placeholder written over plaintext secrets pulled out of deployment definitions, so the column
# still shows a value existed without exposing it.
REDACTED_SECRET = "[redacted by PostHog]"


def _scrub_definition_secrets(row: dict[str, Any]) -> dict[str, Any]:
    """Redact plaintext secrets embedded in a deployment `definition` in place.

    `definition.env[].value` is a plaintext environment value and `definition.config_files[].content`
    is raw config-file content — both can hold credentials. We keep the surrounding structure (env
    keys, secret *references*, file paths) so the row stays useful, but overwrite the secret-bearing
    values. Anything that isn't shaped as expected is left untouched.
    """
    definition = row.get("definition")
    if not isinstance(definition, dict):
        return row

    env = definition.get("env")
    if isinstance(env, list):
        for var in env:
            # `secret` is only a reference to a Koyeb secret name (safe); `value` is the plaintext.
            if isinstance(var, dict) and var.get("value") is not None:
                var["value"] = REDACTED_SECRET

    config_files = definition.get("config_files")
    if isinstance(config_files, list):
        for config_file in config_files:
            if isinstance(config_file, dict) and config_file.get("content") is not None:
                config_file["content"] = REDACTED_SECRET

    return row


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _format_time_value(value: Any) -> str:
    """Format an incremental cursor as the RFC 3339 UTC timestamp Koyeb's date-time params expect."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    return str(value)


def _build_params(
    config: KoyebEndpointConfig,
    offset: int,
    starting_time_value: Any,
    ending_time_value: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE, "offset": offset}

    if config.supports_order:
        params["order"] = "asc"

    if config.requires_time_window:
        params["starting_time"] = USAGE_WINDOW_START
        params["ending_time"] = ending_time_value or _format_time_value(datetime.now(UTC))
    elif config.starting_time_param and starting_time_value is not None:
        params[config.starting_time_param] = _format_time_value(starting_time_value)

    return params


def _build_url(path: str, params: dict[str, Any]) -> str:
    return f"{KOYEB_BASE_URL}{path}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type((KoyebRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    # Koyeb publishes no rate limits; treat 429 and any 5xx as transient and let tenacity back
    # off. A bad/revoked token (401/403) is raised below via raise_for_status() and matched by
    # get_non_retryable_errors() so the sync stops.
    if response.status_code == 429 or response.status_code >= 500:
        raise KoyebRetryableError(f"Koyeb API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Koyeb API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Confirm the API token is genuine via GET /v1/account/profile — the cheapest authenticated
    probe. Koyeb tokens are organization-scoped with no per-resource permissions, so one probe
    covers every endpoint."""
    try:
        response = make_tracked_session().get(
            f"{KOYEB_BASE_URL}/v1/account/profile", headers=_get_headers(api_token), timeout=10
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid or unauthorized Koyeb API token"
    return False, f"Koyeb API error: {response.status_code}"


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KoyebResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = KOYEB_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    # One session reused across every page so urllib3 keeps the connection alive. Endpoints whose
    # rows get secret-scrubbed also opt out of HTTP sample capture: capture stores the raw response
    # body before _scrub_definition_secrets runs, and the capture path's name-based scrubbers can't
    # recognise plaintext env values or config-file content.
    session = make_tracked_session(capture=not config.scrub_definition_secrets)

    cutoff = (
        db_incremental_field_last_value
        if (should_use_incremental_field and config.starting_time_param and db_incremental_field_last_value is not None)
        else None
    )
    # Fixed once per run so the window (and therefore the row set behind the offsets) doesn't
    # drift while paginating.
    ending_time = _format_time_value(datetime.now(UTC)) if config.requires_time_window else None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume else 0
    if resume is not None:
        logger.debug(f"Koyeb: resuming {endpoint} from offset={offset}")

    page_count = 0
    while True:
        url = _build_url(config.path, _build_params(config, offset, cutoff, ending_time))
        data = _fetch_page(session, url, headers, logger)

        items = data.get(config.response_data_key) or []
        if not items:
            break

        if config.scrub_definition_secrets:
            for item in items:
                if isinstance(item, dict):
                    _scrub_definition_secrets(item)

        # Some Koyeb replies carry `has_next`; the rest only echo pagination params, so a short
        # page is the fallback end-of-list signal (an exact-multiple total costs one extra empty
        # page, caught above).
        has_next = data.get("has_next")
        is_last_page = has_next is False or (has_next is None and len(items) < PAGE_SIZE)

        yield items
        offset += len(items)
        page_count += 1

        if is_last_page:
            break
        if page_count >= MAX_PAGES:
            logger.warning(f"Koyeb: {endpoint} hit MAX_PAGES={MAX_PAGES}; remaining pages skipped")
            break
        # Checkpoint AFTER the page has been yielded so a crash re-fetches at most the in-flight
        # page instead of skipping it.
        resumable_source_manager.save_state(KoyebResumeConfig(offset=offset))


def koyeb_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KoyebResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = KOYEB_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Endpoints with an `order` param are requested ascending; the rest are full refresh only,
        # where the watermark is never consulted.
        sort_mode="asc",
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
