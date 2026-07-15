import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.settings import (
    LAMBDA_LABS_ENDPOINTS,
    LambdaLabsEndpoint,
)

# cloud.lambdalabs.com is a deprecated alias for the same API.
LAMBDA_LABS_BASE_URL = "https://cloud.lambda.ai/api/v1"


class LambdaLabsRetryableError(Exception):
    pass


@dataclasses.dataclass
class LambdaLabsResumeConfig:
    # The `page_token` cursor of the next page to fetch. Lambda's cursor already encodes the query
    # window (the incremental `start` filter is only sent on the first request), so the token alone
    # is enough to resume mid-endpoint.
    page_token: str


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _format_iso8601(value: Any) -> str:
    """Format a datetime/date as an ISO 8601 UTC timestamp with a `Z` suffix (millisecond precision),
    which the Lambda API's `start`/`end` filters accept."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return _format_iso8601(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _dig(data: dict[str, Any], dotted_path: str) -> Any:
    """Resolve a dotted key path within a nested response body, returning None if any hop is missing."""
    current: Any = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _flatten_instance_type(value: dict[str, Any]) -> dict[str, Any]:
    """Turn one `/instance-types` map value into a flat row.

    The endpoint returns `data` as an object keyed by instance-type name; each value nests the
    catalog entry under `instance_type` alongside `regions_with_capacity_available`. We hoist the
    `instance_type` fields (which include `name`, the primary key) to the top level and keep the
    regional availability alongside them.

    A missing or malformed `instance_type` raises rather than yielding a row without its primary
    key, which would otherwise surface later as a warehouse load failure or a keyless bad row.
    """
    row = dict(value["instance_type"])
    row["regions_with_capacity_available"] = value.get("regions_with_capacity_available", [])
    return row


# `/instances` records carry a live JupyterLab access token (`jupyter_token`) and a URL that
# embeds the same token (`jupyter_url`). Either grants terminal access to the running instance, so
# they must never land in the warehouse where any project member with read access could retrieve
# them. Stripped from every record defensively, regardless of endpoint.
_SENSITIVE_FIELDS: frozenset[str] = frozenset({"jupyter_token", "jupyter_url"})


def _scrub_sensitive(record: dict[str, Any]) -> dict[str, Any]:
    if _SENSITIVE_FIELDS.isdisjoint(record):
        return record
    return {key: value for key, value in record.items() if key not in _SENSITIVE_FIELDS}


def _extract_records(data: dict[str, Any], endpoint: LambdaLabsEndpoint) -> list[dict[str, Any]]:
    if endpoint.is_map:
        raw_map = data.get("data") or {}
        records = [_flatten_instance_type(value) for value in raw_map.values()]
    else:
        records = _dig(data, endpoint.records_path) or []
    return [_scrub_sensitive(record) for record in records]


@retry(
    # ChunkedEncodingError is a mid-stream connection break (truncated chunked body); it's transient
    # like ConnectionError/ReadTimeout but not a ConnectionError subclass, so list it explicitly.
    retry=retry_if_exception_type(
        (
            LambdaLabsRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    # Lambda rate-limits to ~1 request/second; the jittered backoff also absorbs 429s without a
    # hardcoded inter-request sleep.
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    params: dict[str, str],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, headers=headers, params=params or None, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise LambdaLabsRetryableError(f"Lambda API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Lambda API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LambdaLabsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = LAMBDA_LABS_ENDPOINTS[endpoint]
    session = make_tracked_session()
    headers = _get_headers(api_key)
    url = f"{LAMBDA_LABS_BASE_URL}{config.path}"

    params: dict[str, str] = {}
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if resume is not None and resume.page_token:
        # Mid-endpoint resume: the cursor already encodes the query window, so only the token is sent.
        params = {"page_token": resume.page_token}
        logger.debug(f"Lambda: resuming {endpoint} from page_token")
    elif config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
        # `start` is inclusive, so the boundary event is re-fetched and deduped on the primary key.
        params["start"] = _format_iso8601(db_incremental_field_last_value)

    while True:
        data = _fetch_page(session, url, headers, params, logger)

        records = _extract_records(data, config)
        if records:
            yield records

        next_token = _dig(data, config.page_token_path) if config.page_token_path else None
        if not next_token:
            break

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it; merge
        # dedupes the overlap on the primary key.
        resumable_source_manager.save_state(LambdaLabsResumeConfig(page_token=str(next_token)))
        # The cursor carries the window forward; subsequent pages send only the token.
        params = {"page_token": str(next_token)}


def lambda_labs_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LambdaLabsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = LAMBDA_LABS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # audit-events pages forward from `start` via an ascending timestamp cursor; the unpaginated
        # full-refresh endpoints don't use the watermark, so asc is a safe default for them too.
        sort_mode="asc",
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is accepted with one cheap, account-wide read (`/ssh-keys`).

    Returns False only on a definitive auth rejection (401/403). A network error, timeout, or
    5xx propagates so the caller can tell an invalid key apart from a temporary Lambda outage
    rather than reporting the latter as an invalid key.
    """
    response = make_tracked_session().get(
        f"{LAMBDA_LABS_BASE_URL}/ssh-keys",
        headers=_get_headers(api_key),
        timeout=10,
    )
    if response.status_code in (401, 403):
        return False
    response.raise_for_status()
    return True
