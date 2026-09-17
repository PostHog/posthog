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

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_anomaly_detection.settings import (
    ANOMALY_RETENTION_DAYS,
    AWS_COST_ANOMALY_DETECTION_ENDPOINTS,
    CE_CONTENT_TYPE,
    CE_ENDPOINT_URL,
    CE_SIGNING_NAME,
    CE_SIGNING_REGION,
    CE_TARGET_PREFIX,
    ONGOING_ANOMALY_LOOKBACK_DAYS,
    REQUEST_TIMEOUT_SECONDS,
    AnomalyDetectionEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

MAX_THROTTLE_ATTEMPTS = 6

# Cost Explorer is a POST-only JSON RPC, and the tracked session's default policy only retries
# idempotent verbs — so opt POST in explicitly for the transport-level statuses.
TRANSPORT_RETRY = BoundedRetry(
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

# Codes that mean the key itself is bad, as opposed to a valid key missing an IAM permission.
CREDENTIAL_ERROR_CODES = (
    "UnrecognizedClientException",
    "InvalidClientTokenId",
    "SignatureDoesNotMatch",
    "InvalidSignatureException",
    "ExpiredTokenException",
)

# Cost Explorer serves nothing until it has been enabled once in the console (it can't be enabled
# through the API) and it takes up to 24 hours to prepare data. That arrives as a data-unavailable
# error rather than an empty list, so it gets its own message instead of reading as a bad key.
DATA_UNAVAILABLE_ERROR_CODES = ("DataUnavailableException", "BillExpirationException")

ENABLEMENT_MESSAGE = (
    "AWS has no Cost Explorer data for this account yet. Enable Cost Explorer in the AWS console, "
    "then try again in up to 24 hours once AWS has prepared the data."
)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

_IAM_ACTION_PATTERN = re.compile(r"ce:[A-Za-z0-9]+")


class AwsCostAnomalyDetectionError(Exception):
    pass


class AwsCostAnomalyDetectionThrottledError(AwsCostAnomalyDetectionError):
    pass


@dataclasses.dataclass(frozen=True)
class AwsCostAnomalyDetectionResumeConfig:
    """Where a previous attempt stopped: the date the window started on, plus its page token."""

    date_interval_start: Optional[str] = None
    next_page_token: Optional[str] = None


def _snake(name: str) -> str:
    """`AnomalyStartDate` -> `anomaly_start_date`, `TotalImpactPercentage` -> `total_impact_percentage`."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def _parse_date(value: Any) -> Any:
    """Cost Explorer dates are `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SSZ`; keep anything else untouched."""
    if not isinstance(value, str) or not value:
        return value
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
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


def _flatten(prefix: str, obj: dict[str, Any], raw_keys: frozenset[str]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in obj.items():
        column = f"{prefix}_{_snake(key)}" if prefix else _snake(key)
        if key in raw_keys:
            flattened[column] = value
        elif isinstance(value, dict):
            flattened.update(_flatten(column, value, raw_keys))
        elif isinstance(value, list):
            flattened[column] = [_flatten("", item, raw_keys) if isinstance(item, dict) else item for item in value]
        else:
            flattened[column] = value
    return flattened


def normalize_row(endpoint_config: AnomalyDetectionEndpointConfig, obj: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested structures into snake_case columns and parse the date members."""
    row = _flatten("", obj, endpoint_config.raw_keys)
    for column in endpoint_config.date_columns:
        if column in row:
            row[column] = _parse_date(row[column])
    return row


def resolve_date_interval_start(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    today: dt.date,
) -> dt.date:
    """The earliest `AnomalyEndDate` this run asks AWS for.

    Never earlier than the 90-day retention floor, and an incremental run rewinds behind the
    stored watermark so anomalies AWS is still updating get re-read and re-merged.
    """
    floor = today - dt.timedelta(days=ANOMALY_RETENTION_DAYS)
    if not should_use_incremental_field:
        return floor

    watermark = coerce_date(db_incremental_field_last_value)
    if watermark is None:
        return floor
    return max(floor, min(watermark - dt.timedelta(days=ONGOING_ANOMALY_LOOKBACK_DAYS), today))


def build_payload(
    endpoint_config: AnomalyDetectionEndpointConfig,
    date_interval_start: Optional[dt.date],
    page_token: Optional[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {"MaxResults": endpoint_config.page_size}
    if endpoint_config.supports_date_interval and date_interval_start is not None:
        # `EndDate` is left off deliberately: an anomaly that is still open has its `AnomalyEndDate`
        # pushed forward by AWS, and an open-ended window can't drop it.
        payload["DateInterval"] = {"StartDate": date_interval_start.isoformat()}
    if page_token:
        payload["NextPageToken"] = page_token
    return payload


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


def error_for_response(response: requests.Response) -> AwsCostAnomalyDetectionError:
    code = _error_code(response)
    text = f"AWS Cost Anomaly Detection request failed: {code} - {_error_message(response)}"
    # 429/5xx are already retried by the tracked transport; only the app-level throttling codes
    # (returned as HTTP 400) need a second, bounded retry here.
    if code in THROTTLING_ERROR_CODES:
        return AwsCostAnomalyDetectionThrottledError(text)
    return AwsCostAnomalyDetectionError(text)


def make_session(secret_access_key: str, session_token: Optional[str]) -> requests.Session:
    redact = tuple(value for value in (secret_access_key, session_token) if value)
    return make_tracked_session(retry=TRANSPORT_RETRY, redact_values=redact)


@retry(
    retry=retry_if_exception_type(AwsCostAnomalyDetectionThrottledError),
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


def make_credentials(
    aws_access_key_id: str, aws_secret_access_key: str, aws_session_token: Optional[str]
) -> Credentials:
    return Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None)


def get_rows(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[AwsCostAnomalyDetectionResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = AWS_COST_ANOMALY_DETECTION_ENDPOINTS[endpoint]
    session = make_session(aws_secret_access_key, aws_session_token)
    credentials = make_credentials(aws_access_key_id, aws_secret_access_key, aws_session_token)

    date_interval_start: Optional[dt.date] = None
    if endpoint_config.supports_date_interval:
        date_interval_start = resolve_date_interval_start(
            should_use_incremental_field, db_incremental_field_last_value, dt.datetime.now(dt.UTC).date()
        )
    window_start = date_interval_start.isoformat() if date_interval_start is not None else None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    # A token only belongs to the window it was issued for, so a saved window that no longer
    # matches this run's window restarts the walk.
    page_token = resume.next_page_token if resume is not None and resume.date_interval_start == window_start else None
    resumed_token = page_token is not None
    if resumed_token:
        logger.debug(f"Resuming AWS Cost Anomaly Detection sync from a saved page token. endpoint={endpoint}")

    while True:
        try:
            body = send_operation(
                session,
                credentials,
                endpoint_config.operation,
                build_payload(endpoint_config, date_interval_start, page_token),
            )
        except AwsCostAnomalyDetectionError as error:
            # A token saved by a previous attempt can expire; restart the walk instead of failing
            # the job. Merge on the primary key absorbs the re-read rows.
            if resumed_token and "InvalidNextTokenException" in str(error):
                logger.debug(f"Saved page token no longer valid; restarting. endpoint={endpoint}")
                page_token = None
                resumed_token = False
                resumable_source_manager.clear_state()
                continue
            raise
        resumed_token = False

        rows = [normalize_row(endpoint_config, item) for item in body.get(endpoint_config.result_key) or []]
        if rows:
            yield rows

        page_token = body.get("NextPageToken")
        # Saved after yielding: a crash re-yields the last page, which merges away on the primary
        # key, rather than skipping it.
        resumable_source_manager.save_state(
            AwsCostAnomalyDetectionResumeConfig(date_interval_start=window_start, next_page_token=page_token)
        )
        if not page_token:
            break

    resumable_source_manager.clear_state()


def _permission_reason(error: AwsCostAnomalyDetectionError) -> Optional[str]:
    text = str(error)
    if "AccessDeniedException" in text:
        match = _IAM_ACTION_PATTERN.search(text)
        if match:
            return f"Missing IAM permission {match.group(0)}"
        return "The connected IAM user or role is not allowed to read this table"
    if any(code in text for code in DATA_UNAVAILABLE_ERROR_CODES):
        return ENABLEMENT_MESSAGE
    if any(code in text for code in CREDENTIAL_ERROR_CODES):
        return "AWS rejected the access key. Please check the access key ID and secret access key."
    return None


def endpoint_permission_reason(
    session: requests.Session,
    credentials: Credentials,
    endpoint_config: AnomalyDetectionEndpointConfig,
) -> Optional[str]:
    """Probe the operation a sync of this endpoint calls. `None` when reachable.

    Only a real denial counts as unreachable: throttles, 5xx and network errors leave the endpoint
    reported as reachable, so a blip can't hide tables from the schema picker.
    """
    payload: dict[str, Any] = {"MaxResults": 1}
    if endpoint_config.supports_date_interval:
        yesterday = dt.datetime.now(dt.UTC).date() - dt.timedelta(days=1)
        payload["DateInterval"] = {"StartDate": yesterday.isoformat()}

    try:
        send_operation(session, credentials, endpoint_config.operation, payload)
    except AwsCostAnomalyDetectionError as error:
        return _permission_reason(error)
    except Exception:
        return None
    return None


def probe_endpoint_permissions(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    endpoints: list[str],
) -> dict[str, str | None]:
    session = make_session(aws_secret_access_key, aws_session_token)
    credentials = make_credentials(aws_access_key_id, aws_secret_access_key, aws_session_token)

    reasons: dict[str, str | None] = {}
    for endpoint in endpoints:
        endpoint_config = AWS_COST_ANOMALY_DETECTION_ENDPOINTS.get(endpoint)
        reasons[endpoint] = (
            endpoint_permission_reason(session, credentials, endpoint_config) if endpoint_config is not None else None
        )
    return reasons


def validate_credentials(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    schema_name: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    if not aws_access_key_id or not aws_secret_access_key:
        return False, "AWS access key ID and secret access key are required"

    session = make_session(aws_secret_access_key, aws_session_token)
    credentials = make_credentials(aws_access_key_id, aws_secret_access_key, aws_session_token)

    if schema_name is not None and schema_name in AWS_COST_ANOMALY_DETECTION_ENDPOINTS:
        reason = endpoint_permission_reason(session, credentials, AWS_COST_ANOMALY_DETECTION_ENDPOINTS[schema_name])
        return reason is None, reason

    try:
        send_operation(
            session, credentials, AWS_COST_ANOMALY_DETECTION_ENDPOINTS["anomaly_monitors"].operation, {"MaxResults": 1}
        )
    except AwsCostAnomalyDetectionError as error:
        text = str(error)
        if any(code in text for code in DATA_UNAVAILABLE_ERROR_CODES):
            return False, ENABLEMENT_MESSAGE
        # A denied read still proves the key is genuine; per-table access is reported in the schema
        # picker instead of blocking source creation.
        if "AccessDeniedException" in text:
            return True, None
        return False, text
    except Exception:
        return False, "Could not reach the AWS Cost Explorer API"

    return True, None


def aws_cost_anomaly_detection_source(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[AwsCostAnomalyDetectionResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    endpoint_config = AWS_COST_ANOMALY_DETECTION_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
            endpoint=endpoint,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            logger=logger,
        ),
        primary_keys=endpoint_config.primary_key,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        # AWS documents no ordering for GetAnomalies, so the incremental watermark must only commit
        # once the walk completes; "desc" gives exactly that single end-of-run commit.
        sort_mode="desc",
    )
