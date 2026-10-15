import re
import json
import datetime as dt
import dataclasses
from collections.abc import Iterator
from functools import cache
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.loaders import Loader
from botocore.model import OperationModel, ServiceModel
from botocore.parsers import create_parser
from botocore.serialize import create_serializer
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_cloudwatch.settings import (
    ALARMS_PAGE_SIZE,
    AMAZON_CLOUDWATCH_ENDPOINTS,
    LOG_EVENTS_PAGE_SIZE,
    LOG_GROUPS_PAGE_SIZE,
    LOGS_SERVICE,
    MAX_DISCOVERED_LOG_GROUPS,
    METRIC_DATA_MAX_DATAPOINTS,
    MONITORING_MODEL_NAME,
    MONITORING_SERVICE,
    AwsService,
    CloudWatchEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

REQUEST_TIMEOUT_SECONDS = 120
MAX_THROTTLE_ATTEMPTS = 6

# Both APIs are POST-only RPCs, and the tracked session's default policy only retries idempotent
# verbs, so POST is opted in explicitly for the transport-level statuses.
TRANSPORT_RETRY = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["POST"]),
    raise_on_status=False,
)

# AWS answers these as HTTP 400 with the code in the body, so the transport cannot see them.
THROTTLING_ERROR_CODES = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "RequestLimitExceeded",
        "TooManyRequestsException",
        "LimitExceededException",
    }
)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_REGION = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d$")

ALARM_TYPES = ["CompositeAlarm", "MetricAlarm"]


class AmazonCloudWatchError(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class AmazonCloudWatchThrottledError(AmazonCloudWatchError):
    pass


@dataclasses.dataclass(frozen=True)
class AmazonCloudWatchResumeConfig:
    """Where a previous attempt stopped: the slice (a log group, or a window start) and its page token."""

    slice_key: Optional[str] = None
    next_token: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class TimeWindow:
    start: dt.datetime
    end: dt.datetime


def _snake(name: str) -> str:
    """`AlarmConfigurationUpdatedTimestamp` -> `alarm_configuration_updated_timestamp`."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def _snake_keys(obj: dict[str, Any]) -> dict[str, Any]:
    return {_snake(key): value for key, value in obj.items()}


def _from_millis(value: Any) -> Optional[dt.datetime]:
    if value is None:
        return None
    return dt.datetime.fromtimestamp(int(value) / 1000, tz=dt.UTC)


def _to_millis(value: dt.datetime) -> int:
    return int(value.timestamp() * 1000)


def _as_utc(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def coerce_datetime(value: Any) -> Optional[dt.datetime]:
    if isinstance(value, dt.datetime):
        return _as_utc(value)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, tzinfo=dt.UTC)
    if isinstance(value, str) and value:
        try:
            return _as_utc(dt.datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def is_valid_region(region: str) -> bool:
    return bool(_REGION.match(region.strip()))


def parse_log_group_names(raw: Optional[str]) -> list[str]:
    """One log group per line; blank lines and surrounding whitespace are ignored."""
    if not raw:
        return []
    names = [line.strip() for line in raw.splitlines()]
    return list(dict.fromkeys(name for name in names if name))


def parse_metric_queries(raw: Optional[str]) -> list[dict[str, Any]]:
    """The metric queries field, as GetMetricData `MetricDataQueries`.

    Accepts the API shape (`Id`, `MetricStat`/`Expression`) as well as a flatter one
    (`id`, `namespace`, `metric_name`, `dimensions`, `stat`, `period`) that is easier to type.
    Raises `ValueError` with a message fit for the setup wizard.
    """
    if not raw or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except ValueError as error:
        raise ValueError(f"Metric queries must be valid JSON: {error}") from error
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise ValueError("Metric queries must be a JSON list of query objects.")

    queries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(parsed, start=1):
        if "MetricStat" in item or "Expression" in item:
            query = dict(item)
            query.setdefault("Id", f"q{index}")
        else:
            query = _metric_query_from_flat(item, index)
        query_id = str(query["Id"])
        if query_id in seen:
            raise ValueError(f"Metric query ids must be unique: '{query_id}' is used twice.")
        seen.add(query_id)
        query.setdefault("ReturnData", True)
        queries.append(query)
    return queries


def _metric_query_from_flat(item: dict[str, Any], index: int) -> dict[str, Any]:
    query_id = str(item.get("id") or f"q{index}")
    if "expression" in item:
        query: dict[str, Any] = {"Id": query_id, "Expression": item["expression"]}
        if item.get("period"):
            query["Period"] = int(item["period"])
    else:
        namespace = item.get("namespace")
        metric_name = item.get("metric_name") or item.get("metricName")
        if not namespace or not metric_name:
            raise ValueError(f"Metric query {index} needs a namespace and a metric_name (or an expression).")
        dimensions = item.get("dimensions") or {}
        if isinstance(dimensions, dict):
            dimension_list = [{"Name": str(name), "Value": str(value)} for name, value in dimensions.items()]
        else:
            dimension_list = [
                {"Name": str(d.get("name") or d.get("Name")), "Value": str(d.get("value") or d.get("Value"))}
                for d in dimensions
            ]
        metric: dict[str, Any] = {"Namespace": namespace, "MetricName": metric_name}
        if dimension_list:
            metric["Dimensions"] = dimension_list
        query = {
            "Id": query_id,
            "MetricStat": {
                "Metric": metric,
                "Period": int(item.get("period") or 300),
                "Stat": item.get("stat") or "Average",
            },
        }
        if item.get("unit"):
            query["MetricStat"]["Unit"] = item["unit"]
    if item.get("label"):
        query["Label"] = item["label"]
    return query


@cache
def _service_model(service: AwsService) -> ServiceModel:
    model_name = MONITORING_MODEL_NAME if service == MONITORING_SERVICE else service
    return ServiceModel(Loader().load_service_model(model_name, "service-2"), service_name=model_name)


def _operation(service: AwsService, operation: str) -> OperationModel:
    return _service_model(service).operation_model(operation)


def make_session(secret_access_key: str, session_token: Optional[str]) -> requests.Session:
    redact = tuple(value for value in (secret_access_key, session_token) if value)
    return make_tracked_session(retry=TRANSPORT_RETRY, redact_values=redact)


def _error_from(parsed: dict[str, Any], status_code: int) -> AmazonCloudWatchError:
    error = parsed.get("Error") or {}
    code = str(error.get("Code") or f"HTTP {status_code}").split("#")[-1]
    message = str(error.get("Message") or "")[:500]
    text = f"Amazon CloudWatch request failed: {code} - {message}"
    if code in THROTTLING_ERROR_CODES:
        return AmazonCloudWatchThrottledError(text, code)
    return AmazonCloudWatchError(text, code)


@retry(
    retry=retry_if_exception_type(AmazonCloudWatchThrottledError),
    stop=stop_after_attempt(MAX_THROTTLE_ATTEMPTS),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def send_operation(
    session: requests.Session,
    credentials: Credentials,
    region: str,
    service: AwsService,
    operation: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Serialize one API call from its botocore model, sign it with SigV4 and send it over the tracked session.

    The Logs API is JSON; the CloudWatch metrics API is the older query protocol (form-encoded
    request, XML response). The service model drives both, so neither needs hand-written parsing.
    """
    model = _service_model(service)
    operation_model = _operation(service, operation)
    serialized = create_serializer(model.protocol, include_validation=False).serialize_to_request(
        params, operation_model
    )
    body = serialized["body"]
    if isinstance(body, dict):
        body = urlencode(body).encode()
    elif isinstance(body, str):
        body = body.encode()
    url = f"https://{model.endpoint_prefix}.{region}.amazonaws.com{serialized['url_path']}"

    aws_request = AWSRequest(method="POST", url=url, data=body, headers=dict(serialized["headers"]))
    SigV4Auth(credentials, model.signing_name, region).add_auth(aws_request)

    response = session.post(url, data=body, headers=dict(aws_request.headers.items()), timeout=REQUEST_TIMEOUT_SECONDS)

    output_shape = operation_model.output_shape
    assert output_shape is not None  # every operation this source calls returns a body
    parsed = create_parser(model.protocol).parse(
        {"status_code": response.status_code, "headers": dict(response.headers), "body": response.content},
        output_shape,
    )
    if response.status_code >= 400 or "Error" in parsed:
        raise _error_from(parsed, response.status_code)
    parsed.pop("ResponseMetadata", None)
    return parsed


# AWS error code -> the message the setup wizard shows. A denial names the calling identity's
# IAM ARN, so the raw AWS text never reaches the user.
VALIDATION_ERROR_MESSAGES: dict[str, str] = {
    "UnrecognizedClientException": "AWS rejected the access key. Check the access key ID and secret access key, and that the key is still active.",
    "InvalidClientTokenId": "AWS rejected the access key. Check the access key ID and secret access key, and that the key is still active.",
    "SignatureDoesNotMatch": "AWS rejected the request signature. Re-enter the secret access key.",
    "InvalidSignatureException": "AWS rejected the request signature. If you are using temporary credentials, the session token has expired.",
    "ExpiredTokenException": "The AWS session token has expired. Reconnect with fresh credentials.",
    "ExpiredToken": "The AWS session token has expired. Reconnect with fresh credentials.",
    "AccessDeniedException": "These AWS credentials cannot read CloudWatch. Grant logs:DescribeLogGroups, logs:FilterLogEvents, cloudwatch:DescribeAlarms, cloudwatch:DescribeAlarmHistory and cloudwatch:GetMetricData to the IAM user or role.",
    "AccessDenied": "These AWS credentials cannot read CloudWatch. Grant logs:DescribeLogGroups, logs:FilterLogEvents, cloudwatch:DescribeAlarms, cloudwatch:DescribeAlarmHistory and cloudwatch:GetMetricData to the IAM user or role.",
}

TRANSIENT_VALIDATION_ERROR = "Amazon CloudWatch is busy or temporarily unavailable. Wait a moment and try again."

GENERIC_VALIDATION_ERROR = (
    "AWS didn't accept the CloudWatch request. Check the access key is active and can read CloudWatch, then try again."
)


def validate_credentials(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    aws_region: str,
    metric_queries: Optional[str],
) -> tuple[bool, Optional[str]]:
    """One cheap `DescribeLogGroups` probe, plus a local check of the metric queries JSON."""
    if not aws_access_key_id or not aws_secret_access_key:
        return False, "AWS access key ID and secret access key are required"
    if not aws_region or not is_valid_region(aws_region):
        return False, "Enter an AWS region code, for example us-east-1."
    try:
        parse_metric_queries(metric_queries)
    except ValueError as error:
        return False, str(error)

    try:
        send_operation(
            make_session(aws_secret_access_key, aws_session_token),
            Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None),
            aws_region.strip(),
            LOGS_SERVICE,
            "DescribeLogGroups",
            {"limit": 1},
        )
    except AmazonCloudWatchError as error:
        code = error.code or ""
        if code in VALIDATION_ERROR_MESSAGES:
            return False, VALIDATION_ERROR_MESSAGES[code]
        if code in THROTTLING_ERROR_CODES or code.startswith("HTTP 5"):
            return False, TRANSIENT_VALIDATION_ERROR
        capture_exception(error)
        return False, GENERIC_VALIDATION_ERROR
    except Exception:
        return False, "Could not reach Amazon CloudWatch. Check the region and try again."

    return True, None


def resolve_window(
    endpoint_config: CloudWatchEndpointConfig,
    configured_start_date: Optional[str],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    now: dt.datetime,
) -> TimeWindow:
    """The time range this run asks AWS for: the watermark on an incremental run, else the start
    date, else the endpoint's default lookback. Never before the configured start date."""
    lookback = dt.timedelta(days=endpoint_config.lookback_days or 0)
    floor = coerce_datetime(configured_start_date) or (now - lookback)
    start = floor
    if should_use_incremental_field:
        watermark = coerce_datetime(db_incremental_field_last_value)
        if watermark is not None:
            start = max(floor, watermark)
    return TimeWindow(start=min(start, now), end=now)


def build_windows(window: TimeWindow, window_days: Optional[int]) -> list[TimeWindow]:
    if window_days is None:
        return [window]
    windows: list[TimeWindow] = []
    cursor = window.start
    step = dt.timedelta(days=window_days)
    while cursor < window.end:
        stop = min(cursor + step, window.end)
        windows.append(TimeWindow(start=cursor, end=stop))
        cursor = stop
    return windows


class CloudWatchClient:
    def __init__(
        self,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        aws_session_token: Optional[str],
        aws_region: str,
    ) -> None:
        self._session = make_session(aws_secret_access_key, aws_session_token)
        self._credentials = Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None)
        self._region = aws_region.strip()

    def call(self, service: AwsService, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        return send_operation(self._session, self._credentials, self._region, service, operation, params)

    def list_log_group_names(self, limit: int = MAX_DISCOVERED_LOG_GROUPS) -> list[str]:
        names: list[str] = []
        next_token: Optional[str] = None
        while len(names) < limit:
            params: dict[str, Any] = {"limit": min(LOG_GROUPS_PAGE_SIZE, limit - len(names))}
            if next_token:
                params["nextToken"] = next_token
            body = self.call(LOGS_SERVICE, "DescribeLogGroups", params)
            names.extend(group["logGroupName"] for group in body.get("logGroups") or [] if group.get("logGroupName"))
            next_token = body.get("nextToken")
            if not next_token:
                break
        return names


def log_group_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in body.get("logGroups") or []:
        row = _snake_keys(group)
        row["creation_time"] = _from_millis(row.get("creation_time"))
        rows.append(row)
    return rows


def log_event_rows(log_group_name: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "log_group_name": log_group_name,
            "event_id": event.get("eventId"),
            "log_stream_name": event.get("logStreamName"),
            "timestamp": _from_millis(event.get("timestamp")),
            "ingestion_time": _from_millis(event.get("ingestionTime")),
            "message": event.get("message"),
        }
        for event in body.get("events") or []
    ]


def alarm_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for alarm_type, key in (("MetricAlarm", "MetricAlarms"), ("CompositeAlarm", "CompositeAlarms")):
        for alarm in body.get(key) or []:
            row = _snake_keys(alarm)
            row["alarm_type"] = alarm_type
            rows.append(row)
    return rows


def alarm_history_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [_snake_keys(item) for item in body.get("AlarmHistoryItems") or []]


def metric_data_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in body.get("MetricDataResults") or []:
        timestamps = result.get("Timestamps") or []
        values = result.get("Values") or []
        for timestamp, value in zip(timestamps, values):
            rows.append(
                {
                    "query_id": result.get("Id"),
                    "label": result.get("Label"),
                    "timestamp": _as_utc(timestamp),
                    "value": value,
                    "status_code": result.get("StatusCode"),
                }
            )
    return rows


def _slices(
    endpoint_config: CloudWatchEndpointConfig,
    client: CloudWatchClient,
    log_group_names: list[str],
    window: TimeWindow,
) -> list[tuple[str, Optional[str]]]:
    """The request series of one run: (slice key, log group) pairs for logs, window starts otherwise."""
    if endpoint_config.operation == "FilterLogEvents":
        groups = log_group_names or client.list_log_group_names()
        return [(name, name) for name in groups]
    if endpoint_config.lookback_days is None:
        return [("", None)]
    return [(piece.start.isoformat(), None) for piece in build_windows(window, endpoint_config.window_days)]


def _params(
    endpoint_config: CloudWatchEndpointConfig,
    slice_key: str,
    log_group: Optional[str],
    window: TimeWindow,
    metric_queries: list[dict[str, Any]],
    next_token: Optional[str],
) -> dict[str, Any]:
    operation = endpoint_config.operation
    params: dict[str, Any]
    if operation == "DescribeLogGroups":
        params = {"limit": LOG_GROUPS_PAGE_SIZE}
        if next_token:
            params["nextToken"] = next_token
        return params
    if operation == "FilterLogEvents":
        params = {
            "logGroupName": log_group,
            "startTime": _to_millis(window.start),
            "endTime": _to_millis(window.end),
            "limit": LOG_EVENTS_PAGE_SIZE,
        }
        if next_token:
            params["nextToken"] = next_token
        return params
    if operation == "DescribeAlarms":
        params = {"AlarmTypes": ALARM_TYPES, "MaxRecords": ALARMS_PAGE_SIZE}
    elif operation == "DescribeAlarmHistory":
        params = {
            "AlarmTypes": ALARM_TYPES,
            "StartDate": window.start,
            "EndDate": window.end,
            "ScanBy": "TimestampAscending",
            "MaxRecords": ALARMS_PAGE_SIZE,
        }
    else:
        piece = next(
            (w for w in build_windows(window, endpoint_config.window_days) if w.start.isoformat() == slice_key),
            window,
        )
        params = {
            "MetricDataQueries": metric_queries,
            "StartTime": piece.start,
            "EndTime": piece.end,
            "ScanBy": "TimestampAscending",
            "MaxDatapoints": METRIC_DATA_MAX_DATAPOINTS,
        }
    if next_token:
        params["NextToken"] = next_token
    return params


def _rows(
    endpoint_config: CloudWatchEndpointConfig, log_group: Optional[str], body: dict[str, Any]
) -> list[dict[str, Any]]:
    operation = endpoint_config.operation
    if operation == "DescribeLogGroups":
        return log_group_rows(body)
    if operation == "FilterLogEvents":
        return log_event_rows(log_group or "", body)
    if operation == "DescribeAlarms":
        return alarm_rows(body)
    if operation == "DescribeAlarmHistory":
        return alarm_history_rows(body)
    return metric_data_rows(body)


def _next_token(endpoint_config: CloudWatchEndpointConfig, body: dict[str, Any]) -> Optional[str]:
    return body.get("nextToken") if endpoint_config.service == LOGS_SERVICE else body.get("NextToken")


def get_rows(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    aws_region: str,
    log_group_names: Optional[str],
    metric_queries: Optional[str],
    start_date: Optional[str],
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[AmazonCloudWatchResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = AMAZON_CLOUDWATCH_ENDPOINTS[endpoint]
    client = CloudWatchClient(aws_access_key_id, aws_secret_access_key, aws_session_token, aws_region)

    queries = parse_metric_queries(metric_queries) if endpoint_config.operation == "GetMetricData" else []
    if endpoint_config.operation == "GetMetricData" and not queries:
        logger.info("Amazon CloudWatch metric_data has no metric queries configured, nothing to sync")
        resumable_source_manager.clear_state()
        return

    now = dt.datetime.now(dt.UTC)
    window = resolve_window(
        endpoint_config, start_date, should_use_incremental_field, db_incremental_field_last_value, now
    )
    slices = _slices(endpoint_config, client, parse_log_group_names(log_group_names), window)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    index, next_token = 0, None
    if resume is not None:
        # A saved slice that no longer exists (the window moved, a log group went away) restarts the run.
        for position, (slice_key, _) in enumerate(slices):
            if slice_key == resume.slice_key:
                index, next_token = position, resume.next_token
                logger.debug(f"Resuming Amazon CloudWatch sync. endpoint={endpoint}, slice={slice_key}")
                break

    for slice_key, log_group in slices[index:]:
        while True:
            body = client.call(
                endpoint_config.service,
                endpoint_config.operation,
                _params(endpoint_config, slice_key, log_group, window, queries, next_token),
            )
            rows = _rows(endpoint_config, log_group, body)
            next_token = _next_token(endpoint_config, body)

            # Staged before the batch it covers: a crash after the write resumes at the next page.
            resumable_source_manager.save_state(
                AmazonCloudWatchResumeConfig(slice_key=slice_key, next_token=next_token)
            )
            if rows:
                yield rows
            else:
                # FilterLogEvents often returns empty pages mid-walk; let the pipeline commit and hand off.
                resumable_source_manager.safe_point()

            if not next_token:
                break

    resumable_source_manager.clear_state()


def amazon_cloudwatch_source(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    aws_region: str,
    log_group_names: Optional[str],
    metric_queries: Optional[str],
    start_date: Optional[str],
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[AmazonCloudWatchResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    endpoint_config = AMAZON_CLOUDWATCH_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
            aws_region=aws_region,
            log_group_names=log_group_names,
            metric_queries=metric_queries,
            start_date=start_date,
            endpoint=endpoint,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            logger=logger,
        ),
        primary_keys=endpoint_config.primary_key,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format=endpoint_config.partition_format,
        sort_mode="asc" if endpoint_config.sorted_ascending else None,
    )
