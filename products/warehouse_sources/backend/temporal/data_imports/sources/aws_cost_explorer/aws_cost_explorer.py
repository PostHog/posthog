import re
import json
import datetime as dt
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer.settings import (
    AWS_COST_EXPLORER_ENDPOINTS,
    CE_CONTENT_TYPE,
    CE_ENDPOINT_URL,
    CE_SIGNING_NAME,
    CE_SIGNING_REGION,
    CE_TARGET_PREFIX,
    DEFAULT_LOOKBACK_DAYS,
    CostExplorerEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

REQUEST_TIMEOUT_SECONDS = 120
MAX_THROTTLE_ATTEMPTS = 6

# The Cost Explorer API is a POST-only JSON RPC, and the tracked session's default policy only
# retries idempotent verbs — so opt POST in explicitly for the transport-level statuses.
TRANSPORT_RETRY = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["POST"]),
    raise_on_status=False,
)

# AWS returns these as HTTP 400 with the code in the body, so the transport can't see them.
THROTTLING_ERROR_CODES = frozenset(
    {
        "LimitExceededException",
        "RequestLimitExceeded",
        "ThrottlingException",
        "TooManyRequestsException",
    }
)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


class AwsCostExplorerError(Exception):
    pass


class AwsCostExplorerThrottledError(AwsCostExplorerError):
    pass


@dataclasses.dataclass
class AwsCostExplorerResumeConfig:
    """Where a previous attempt stopped: the request window plus its page token."""

    window_start: str
    next_page_token: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class TimeWindow:
    start: dt.date
    end: dt.date


def _snake(name: str) -> str:
    """`UtilizationPercentage` -> `utilization_percentage`, `LINKED_ACCOUNT` -> `linked_account`."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def _to_number(value: Any) -> Any:
    """Cost Explorer returns every numeric as a string; keep non-numerics untouched."""
    if not isinstance(value, str):
        return value
    try:
        return float(value)
    except ValueError:
        return value


def _parse_period(value: Any) -> Optional[dt.datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)


def coerce_date(value: Any) -> Optional[dt.date]:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value:
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def resolve_start_date(
    configured_start_date: Optional[str],
    endpoint_config: CostExplorerEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    end: dt.date,
) -> dt.date:
    """The earliest date this run asks AWS for.

    Incremental runs rewind behind the stored watermark because Cost Explorer restates recent
    periods until the bill finalizes, but never before the user's configured start date.
    """
    floor = coerce_date(configured_start_date) or (end - dt.timedelta(days=DEFAULT_LOOKBACK_DAYS))

    start = floor
    if should_use_incremental_field:
        watermark = coerce_date(db_incremental_field_last_value)
        if watermark is not None:
            start = max(floor, watermark - dt.timedelta(days=endpoint_config.restatement_lookback_days))

    return min(start, end)


def build_windows(start: dt.date, end: dt.date, window_days: int) -> list[TimeWindow]:
    """Split [start, end) into request windows. `end` is exclusive, matching `TimePeriod`."""
    windows: list[TimeWindow] = []
    cursor = start
    while cursor < end:
        stop = min(cursor + dt.timedelta(days=window_days), end)
        windows.append(TimeWindow(start=cursor, end=stop))
        cursor = stop
    return windows


def build_payload(
    endpoint_config: CostExplorerEndpointConfig, window: TimeWindow, page_token: Optional[str]
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "TimePeriod": {"Start": window.start.isoformat(), "End": window.end.isoformat()},
        "Granularity": endpoint_config.granularity,
    }
    if endpoint_config.metrics:
        payload["Metrics"] = list(endpoint_config.metrics)
    if endpoint_config.group_by:
        payload["GroupBy"] = [{"Type": "DIMENSION", "Key": key} for key in endpoint_config.group_by]
    if page_token and endpoint_config.page_token_key:
        payload[endpoint_config.page_token_key] = page_token
    return payload


def _flatten(prefix: str, obj: dict[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in obj.items():
        column = f"{prefix}_{_snake(key)}" if prefix else _snake(key)
        if isinstance(value, dict):
            flattened.update(_flatten(column, value))
        else:
            flattened[column] = _to_number(value)
    return flattened


def _metric_columns(endpoint_config: CostExplorerEndpointConfig, metrics: dict[str, Any]) -> dict[str, Any]:
    # Driven off the configured metric list rather than the response, so a period AWS omits a
    # metric for still lands with the same columns.
    columns: dict[str, Any] = {}
    for metric in endpoint_config.metrics:
        value = metrics.get(metric) or {}
        columns[f"{_snake(metric)}_amount"] = _to_number(value.get("Amount"))
        columns[f"{_snake(metric)}_unit"] = value.get("Unit")
    return columns


def _cost_rows(
    endpoint_config: CostExplorerEndpointConfig, base: dict[str, Any], result: dict[str, Any]
) -> list[dict[str, Any]]:
    group_columns = [_snake(key) for key in endpoint_config.group_by]
    groups = result.get("Groups") or []

    if not groups:
        row = dict(base)
        row.update(dict.fromkeys(group_columns))
        row.update(_metric_columns(endpoint_config, result.get("Total") or {}))
        return [row]

    rows: list[dict[str, Any]] = []
    for group in groups:
        row = dict(base)
        keys = group.get("Keys") or []
        for index, column in enumerate(group_columns):
            row[column] = keys[index] if index < len(keys) else None
        row.update(_metric_columns(endpoint_config, group.get("Metrics") or {}))
        rows.append(row)
    return rows


def normalize_results(endpoint_config: CostExplorerEndpointConfig, body: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for result in body.get(endpoint_config.result_key) or []:
        period = result.get("TimePeriod") or {}
        base: dict[str, Any] = {
            "period_start": _parse_period(period.get("Start")),
            "period_end": _parse_period(period.get("End")),
            "granularity": endpoint_config.granularity,
        }

        if endpoint_config.metrics:
            # Recent periods come back estimated and are restated later; the lookback rewind
            # re-merges them once finalized. Only the cost operations report it.
            base["estimated"] = result.get("Estimated")
            rows.extend(_cost_rows(endpoint_config, base, result))
            continue

        row = dict(base)
        for member, prefix in endpoint_config.nested_keys:
            row.update(_flatten(prefix, result.get(member) or {}))
        rows.append(row)

    return rows


def _error_code(response: requests.Response) -> str:
    header = response.headers.get("x-amzn-ErrorType") or ""
    if header:
        return header.split(":")[0].split("#")[-1]
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    raw = body.get("__type") or body.get("code") or f"HTTP {response.status_code}"
    return str(raw).split("#")[-1]


def _error_message(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    message = body.get("message") or body.get("Message") or ""
    return str(message)[:500]


def error_for_response(response: requests.Response) -> AwsCostExplorerError:
    code = _error_code(response)
    text = f"AWS Cost Explorer request failed: {code} - {_error_message(response)}"
    # 429/5xx are already retried by the tracked transport; only the app-level throttling codes
    # (returned as HTTP 400) need a second, bounded retry here.
    if code in THROTTLING_ERROR_CODES:
        return AwsCostExplorerThrottledError(text)
    return AwsCostExplorerError(text)


def make_session(secret_access_key: str, session_token: Optional[str]) -> requests.Session:
    redact = tuple(value for value in (secret_access_key, session_token) if value)
    return make_tracked_session(retry=TRANSPORT_RETRY, redact_values=redact)


@retry(
    retry=retry_if_exception_type(AwsCostExplorerThrottledError),
    stop=stop_after_attempt(MAX_THROTTLE_ATTEMPTS),
    wait=wait_exponential_jitter(initial=5, max=120),
    reraise=True,
)
def send_operation(
    session: requests.Session,
    credentials: Credentials,
    operation: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Sign one Cost Explorer JSON-RPC call with SigV4 and send it over the tracked session."""
    body = json.dumps(payload).encode()
    aws_request = AWSRequest(
        method="POST",
        url=CE_ENDPOINT_URL,
        data=body,
        headers={
            "Content-Type": CE_CONTENT_TYPE,
            "X-Amz-Target": f"{CE_TARGET_PREFIX}.{operation}",
        },
    )
    SigV4Auth(credentials, CE_SIGNING_NAME, CE_SIGNING_REGION).add_auth(aws_request)

    response = session.post(
        CE_ENDPOINT_URL,
        data=body,
        headers=dict(aws_request.headers.items()),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code >= 400:
        raise error_for_response(response)

    return response.json()


def validate_credentials(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
) -> tuple[bool, Optional[str]]:
    """One cheap `GetCostAndUsage` probe — the exact permission every table needs."""
    if not aws_access_key_id or not aws_secret_access_key:
        return False, "AWS access key ID and secret access key are required"

    end = dt.datetime.now(dt.UTC).date() + dt.timedelta(days=1)
    payload = {
        "TimePeriod": {"Start": (end - dt.timedelta(days=2)).isoformat(), "End": end.isoformat()},
        "Granularity": "DAILY",
        "Metrics": ["UnblendedCost"],
    }

    try:
        send_operation(
            make_session(aws_secret_access_key, aws_session_token),
            Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None),
            "GetCostAndUsage",
            payload,
        )
    except AwsCostExplorerError as error:
        return False, str(error)
    except Exception:
        return False, "Could not reach the AWS Cost Explorer API"

    return True, None


def _resume_index(
    windows: list[TimeWindow], resume: Optional[AwsCostExplorerResumeConfig]
) -> tuple[int, Optional[str]]:
    """Where to pick up. A saved window that no longer exists (the range moved) restarts the run."""
    if resume is None:
        return 0, None

    for index, window in enumerate(windows):
        if window.start.isoformat() == resume.window_start:
            return index, resume.next_page_token

    return 0, None


def get_rows(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    start_date: Optional[str],
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[AwsCostExplorerResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = AWS_COST_EXPLORER_ENDPOINTS[endpoint]

    session = make_session(aws_secret_access_key, aws_session_token)
    credentials = Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None)

    # `End` is exclusive, so tomorrow captures today's partial (flagged estimated) too.
    end = dt.datetime.now(dt.UTC).date() + dt.timedelta(days=1)
    start = resolve_start_date(
        start_date, endpoint_config, should_use_incremental_field, db_incremental_field_last_value, end
    )
    windows = build_windows(start, end, endpoint_config.window_days)
    if not windows:
        resumable_source_manager.clear_state()
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    index, page_token = _resume_index(windows, resume)
    if resume is not None:
        logger.debug(f"Resuming AWS Cost Explorer sync. endpoint={endpoint}, window={windows[index].start}")

    for window in windows[index:]:
        while True:
            body = send_operation(
                session, credentials, endpoint_config.operation, build_payload(endpoint_config, window, page_token)
            )
            rows = normalize_results(endpoint_config, body)
            if rows:
                yield rows

            page_token = body.get(endpoint_config.page_token_key) if endpoint_config.page_token_key else None
            # Saved after yielding: a crash re-yields the last batch, which merges away on the
            # primary key, rather than skipping it.
            resumable_source_manager.save_state(
                AwsCostExplorerResumeConfig(window_start=window.start.isoformat(), next_page_token=page_token)
            )

            if not page_token:
                break

        page_token = None

    resumable_source_manager.clear_state()


def aws_cost_explorer_source(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    start_date: Optional[str],
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[AwsCostExplorerResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    endpoint_config = AWS_COST_EXPLORER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
            start_date=start_date,
            endpoint=endpoint,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            logger=logger,
        ),
        primary_keys=endpoint_config.primary_key,
        partition_keys=["period_start"],
        partition_mode="datetime",
        partition_format="month",
        sort_mode="asc",
    )
