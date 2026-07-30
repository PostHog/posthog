import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.signoz.settings import (
    SIGNOZ_ENDPOINTS,
    SigNozEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60
DEFAULT_LOOKBACK_DAYS = 30

QUERY_RANGE_PATH = "/api/v5/query_range"

HOST_NOT_ALLOWED_ERROR = "SigNoz host is not allowed"


class SigNozRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class SigNozHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class SigNozResumeConfig:
    """Position within a telemetry sync: the current time window plus the row offset into it.

    ``window_end_ms`` is pinned at sync start so a resume doesn't silently extend the window,
    and ``window_start_ms`` advances to the last yielded row's timestamp after each page so
    offsets stay small (the query_range API's offset paging scans offset+limit rows server-side).
    """

    window_start_ms: int
    window_end_ms: int
    offset: int


def normalize_host(host: str) -> str:
    """Turn whatever the user typed into a bare SigNoz host.

    Accepts values like ``example.signoz.io``, ``https://example.signoz.io/``, or
    ``example.signoz.io/api`` and returns ``example.signoz.io``.
    """
    host = host.strip()
    host = re.sub(r"^https?://", "", host, flags=re.IGNORECASE)
    host = host.split("/")[0]
    return host.strip().rstrip("/")


def _base_url(host: str) -> str:
    return f"https://{normalize_host(host)}"


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "SIGNOZ-API-KEY": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _to_epoch_ms(value: Any) -> int | None:
    """Convert an incremental cursor / row timestamp into epoch milliseconds."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return int(dt.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    if isinstance(value, int | float):
        # Values this large are already epoch milliseconds; smaller ones are epoch seconds.
        return int(value if value >= 1_000_000_000_000 else value * 1000)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
        return int(dt.timestamp() * 1000)
    return None


def validate_credentials(
    host: str, api_key: str, schema_name: Optional[str] = None, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe a cheap list endpoint to confirm the API key is genuine.

    At source-create (``schema_name is None``) a 403 is accepted: the key is valid but its
    service account may lack the role for this particular probe. A scoped probe
    (``schema_name`` set) treats 403 as a hard failure.
    """
    try:
        normalized = normalize_host(host)
    except Exception:
        return False, "Invalid SigNoz host"

    if not normalized or not re.match(r"^[A-Za-z0-9.\-]+$", normalized):
        return False, "Invalid SigNoz host"

    # The host is fully customer-controlled (cloud tenant or self-hosted URL), so block hosts
    # that resolve to private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(normalized, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"https://{normalized}/api/v1/rules"
    try:
        # Don't follow redirects: the validated host could 3xx to an internal address,
        # defeating the host check above (SSRF). capture=False keeps the probe out of HTTP
        # sample capture — the response can echo tokens the name-based scrubber can't catch.
        response = make_tracked_session(redact_values=(api_key,), capture=False).get(
            url, headers=_get_headers(api_key), timeout=10, allow_redirects=False
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid SigNoz API key. Generate a new key from a service account and try again."

    if response.status_code == 403:
        if schema_name is None:
            # Valid key, missing role for this probe — let source creation through.
            return True, None
        return False, "Your SigNoz API key lacks the required permissions for this endpoint."

    return False, f"SigNoz credential validation failed (status {response.status_code})."


def _build_query_range_body(
    config: SigNozEndpointConfig,
    window_start_ms: int,
    window_end_ms: int,
    offset: int,
) -> dict[str, Any]:
    return {
        "start": window_start_ms,
        "end": window_end_ms,
        "requestType": "raw",
        "compositeQuery": {
            "queries": [
                {
                    "type": "builder_query",
                    "spec": {
                        "name": "A",
                        "signal": config.signal,
                        "order": [{"key": {"name": key}, "direction": "asc"} for key in config.order_keys],
                        "offset": offset,
                        "limit": config.page_size,
                    },
                }
            ]
        },
    }


def _extract_raw_rows(response_json: Any) -> list[dict[str, Any]]:
    """Pull the raw rows out of a v5 query_range response.

    Shape: ``{"status": "success", "data": {"type": "raw", "data": {"results":
    [{"queryName": "A", "rows": [{"timestamp": ..., "data": {...}}]}]}}}``.
    """
    data = response_json.get("data") if isinstance(response_json, dict) else None
    inner = data.get("data") if isinstance(data, dict) else None
    results = inner.get("results") if isinstance(inner, dict) else None
    if not isinstance(results, list) or not results:
        return []
    rows = results[0].get("rows") if isinstance(results[0], dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _raw_row_to_item(row: dict[str, Any]) -> dict[str, Any]:
    """Flatten a raw row's ``data`` map to the root, with the envelope timestamp winning.

    The envelope ``timestamp`` is a consistent RFC 3339 string, while the column value's
    format varies by signal, so the envelope value is what we key incremental syncs and
    partitioning on.
    """
    item = dict(row.get("data") or {})
    if row.get("timestamp") is not None:
        item["timestamp"] = row["timestamp"]
    return item


def _extract_config_items(response_json: Any, config: SigNozEndpointConfig) -> list[dict[str, Any]]:
    """Pull records out of a management endpoint response (``{"status": ..., "data": ...}``)."""
    node = response_json.get("data") if isinstance(response_json, dict) else None
    for key in config.data_keys:
        node = node.get(key) if isinstance(node, dict) else None
    if not isinstance(node, list):
        return []
    items = [item for item in node if isinstance(item, dict)]
    if config.allowed_fields is not None:
        # Strict allowlist — drop everything else so credential-bearing fields never leak
        # into the warehouse table (see SigNozEndpointConfig.allowed_fields).
        allowed = set(config.allowed_fields)
        items = [{k: v for k, v in item.items() if k in allowed} for item in items]
    return items


def _parse_retry_after(response: requests.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Honor a server-provided Retry-After when present, else exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, SigNozRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


def _initial_window(
    config: SigNozEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> tuple[int, int]:
    end_ms = int(datetime.now(UTC).timestamp() * 1000)
    start_ms: int | None = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        start_ms = _to_epoch_ms(db_incremental_field_last_value)
    if start_ms is None:
        lookback_days = config.default_lookback_days or DEFAULT_LOOKBACK_DAYS
        start_ms = int((datetime.now(UTC) - timedelta(days=lookback_days)).timestamp() * 1000)
    return start_ms, end_ms


def get_rows(
    host: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SigNozResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SIGNOZ_ENDPOINTS[endpoint]

    # Re-check at run time (not just at source-create) in case the host was edited or now
    # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(normalize_host(host), team_id)
    if not host_ok:
        raise SigNozHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    base = _base_url(host)
    # One tracked session reused across pages and retries; the API key is redacted from
    # logged URLs. capture=False excludes responses from HTTP sample capture: imported log
    # bodies, dashboard/notification config, etc. can carry secrets the name-based scrubber
    # can't reliably strip, so they must never reach the shared sample bucket.
    session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,), capture=False)

    @retry(
        retry=retry_if_exception_type((SigNozRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch(url: str, json_body: dict[str, Any] | None = None) -> Any:
        # Don't follow redirects: an attacker-controlled host could 3xx to an internal
        # address, bypassing the host validation done before the request (SSRF).
        if json_body is not None:
            response = session.post(url, json=json_body, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)
        else:
            response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = _parse_retry_after(response) if response.status_code == 429 else None
            raise SigNozRetryableError(
                f"SigNoz API error (retryable): status={response.status_code}, url={url}",
                retry_after=retry_after,
            )

        # A 3xx isn't an error status (`response.ok` is True), so reject it explicitly rather
        # than silently parsing the redirect body as data.
        if response.is_redirect or response.is_permanent_redirect:
            raise SigNozHostNotAllowedError(
                f"SigNoz API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
            )

        if not response.ok:
            logger.error(f"SigNoz API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    if config.kind == "config":
        items = _extract_config_items(fetch(f"{base}{config.path}"), config)
        if items:
            yield items
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        window_start, window_end, offset = resume.window_start_ms, resume.window_end_ms, resume.offset
        logger.debug(f"SigNoz: resuming {endpoint} at window_start={window_start}, offset={offset}")
    else:
        window_start, window_end = _initial_window(
            config, should_use_incremental_field, db_incremental_field_last_value
        )
        offset = 0

    url = f"{base}{QUERY_RANGE_PATH}"

    while True:
        body = _build_query_range_body(config, window_start, window_end, offset)
        rows = _extract_raw_rows(fetch(url, json_body=body))
        if not rows:
            break

        yield [_raw_row_to_item(row) for row in rows]

        if len(rows) < config.page_size:
            break

        # Advance the window start to the last row's timestamp instead of paging with an
        # ever-growing offset — query_range scans offset+limit rows server-side, so deep
        # offsets get quadratically expensive. The window start is inclusive, so rows sharing
        # the last row's millisecond are re-listed on the next request and skipped via the
        # offset; anything re-yielded across a crash is deduped by primary-key merge.
        last_ts = _to_epoch_ms(rows[-1].get("timestamp"))
        if last_ts is None or last_ts < window_start:
            # No usable timestamp to advance on — fall back to plain offset paging.
            offset += len(rows)
        elif last_ts == window_start:
            # The entire window start millisecond spans multiple pages.
            offset += len(rows)
        else:
            trailing = 0
            for row in reversed(rows):
                if _to_epoch_ms(row.get("timestamp")) == last_ts:
                    trailing += 1
                else:
                    break
            window_start = last_ts
            offset = trailing

        # Save state AFTER yielding the batch — a crash re-yields the last batch (merge
        # dedupes on primary key) instead of skipping it.
        resumable_source_manager.save_state(
            SigNozResumeConfig(window_start_ms=window_start, window_end_ms=window_end, offset=offset)
        )


def signoz_source(
    host: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SigNozResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SIGNOZ_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            api_key=api_key,
            endpoint=endpoint,
            team_id=team_id,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_keys),
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
