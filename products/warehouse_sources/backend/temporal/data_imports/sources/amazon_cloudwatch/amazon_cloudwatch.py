import re
import copy
import json
import hashlib
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
from botocore.parsers import ResponseParserError, create_parser
from botocore.serialize import create_serializer
from botocore.validate import ParamValidator
from structlog.types import FilteringBoundLogger
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    stop_before_delay,
    wait_exponential_jitter,
)

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_cloudwatch.settings import (
    ALARMS_PAGE_SIZE,
    AMAZON_CLOUDWATCH_ENDPOINTS,
    LOG_EVENTS_PAGE_SIZE,
    LOG_GROUPS_PAGE_SIZE,
    LOGS_SERVICE,
    MAX_DISCOVERED_LOG_GROUPS,
    METRIC_DATA_MAX_DATAPOINTS,
    MONITORING_SERVICE,
    SERVICE_MODELS,
    STS_SERVICE,
    AwsService,
    CloudWatchEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import NO_RETRY
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import reach_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# (connect, read) seconds for one try.
REQUEST_TIMEOUT = (10, 60)
MAX_ATTEMPTS = 6
# No try starts after this, so one call with its tries and waits stays under five minutes.
RETRY_BUDGET_SECONDS = 180

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

ALARM_TYPES = ["CompositeAlarm", "MetricAlarm"]


class AmazonCloudWatchError(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class AmazonCloudWatchTransientError(AmazonCloudWatchError):
    pass


class AmazonCloudWatchThrottledError(AmazonCloudWatchTransientError):
    pass


METRIC_QUERY_FORBIDDEN = "MetricQueryForbidden"
METRIC_QUERY_PARTIAL_DATA = "MetricQueryPartialData"
INVALID_METRIC_QUERIES = "Invalid metric queries"
INVALID_START_DATE = "Invalid start date"
# The cursor a slice's last page stages when no slice follows it, so a resumed attempt knows the run is done.
COMPLETED_SLICE = "__complete__"
METRIC_QUERY_INTERNAL_ERROR = "MetricQueryInternalError"
INVALID_REQUEST_ERROR_CODES = frozenset(
    {"InvalidParameterValue", "InvalidParameterCombination", "MissingParameter", "InvalidParameterException"}
)


@dataclasses.dataclass(frozen=True)
class AmazonCloudWatchResumeConfig:
    """Where a previous attempt stopped: the slice (a log group, or a window start), its page token,
    and the time range of the run, so a resumed attempt reads the same range rather than one that
    moved with the clock."""

    slice_key: Optional[str] = None
    next_token: Optional[str] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None


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


@cache
def aws_dns_suffix(region: str) -> Optional[str]:
    """The DNS suffix of the AWS partition a region belongs to, or None for an unknown region.

    China regions live under `amazonaws.com.cn`, so the suffix comes from botocore's partition table.
    """
    for partition in Loader().load_data("partitions")["partitions"]:
        if region in partition.get("regions", {}) or re.match(partition["regionRegex"], region):
            return partition["outputs"]["dnsSuffix"]
    return None


def is_valid_region(region: str) -> bool:
    return aws_dns_suffix(region.strip()) is not None


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
        raise ValueError(f"{INVALID_METRIC_QUERIES}: not valid JSON ({error}).") from error
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise ValueError(f"{INVALID_METRIC_QUERIES}: expected a JSON list of query objects.")

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
            raise ValueError(f"{INVALID_METRIC_QUERIES}: the id '{query_id}' is used twice.")
        seen.add(query_id)
        query.setdefault("ReturnData", True)
        queries.append(query)

    input_shape = _operation(MONITORING_SERVICE, "GetMetricData").input_shape
    assert input_shape is not None  # GetMetricData takes a request body
    report = ParamValidator().validate(
        {
            "MetricDataQueries": queries,
            "StartTime": dt.datetime(2000, 1, 1, tzinfo=dt.UTC),
            "EndTime": dt.datetime(2000, 1, 2, tzinfo=dt.UTC),
        },
        input_shape,
    )
    if report.has_errors():
        raise ValueError(f"{INVALID_METRIC_QUERIES}: they do not match the CloudWatch API. {report.generate_report()}")
    return queries


def _period(value: Any, index: int, default: Optional[int]) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{INVALID_METRIC_QUERIES}: query {index} has a period that is not a whole number of seconds."
        ) from error


def _metric_query_from_flat(item: dict[str, Any], index: int) -> dict[str, Any]:
    query_id = str(item.get("id") or f"q{index}")
    if "expression" in item:
        query: dict[str, Any] = {"Id": query_id, "Expression": item["expression"]}
        expression_period = _period(item.get("period"), index, None)
        if expression_period:
            query["Period"] = expression_period
    else:
        namespace = item.get("namespace")
        metric_name = item.get("metric_name") or item.get("metricName")
        if not namespace or not metric_name:
            raise ValueError(
                f"{INVALID_METRIC_QUERIES}: query {index} needs a namespace and a metric_name, or an expression."
            )
        dimension_list = _dimensions(item.get("dimensions") or {}, index)
        metric: dict[str, Any] = {"Namespace": namespace, "MetricName": metric_name}
        if dimension_list:
            metric["Dimensions"] = dimension_list
        query = {
            "Id": query_id,
            "MetricStat": {
                "Metric": metric,
                "Period": _period(item.get("period"), index, 300),
                "Stat": item.get("stat") or "Average",
            },
        }
        if item.get("unit"):
            query["MetricStat"]["Unit"] = item["unit"]
    if item.get("label"):
        query["Label"] = item["label"]
    return query


def _dimensions(dimensions: Any, index: int) -> list[dict[str, str]]:
    if isinstance(dimensions, dict):
        return [{"Name": str(name), "Value": str(value)} for name, value in dimensions.items()]
    if not isinstance(dimensions, list):
        raise ValueError(
            f"{INVALID_METRIC_QUERIES}: query {index} needs dimensions as an object or a list of name and value pairs."
        )
    dimension_list: list[dict[str, str]] = []
    for dimension in dimensions:
        name = dimension.get("name") or dimension.get("Name") if isinstance(dimension, dict) else None
        value = dimension.get("value") or dimension.get("Value") if isinstance(dimension, dict) else None
        if not name or value is None:
            raise ValueError(f"{INVALID_METRIC_QUERIES}: query {index} has a dimension without a name and a value.")
        dimension_list.append({"Name": str(name), "Value": str(value)})
    return dimension_list


@cache
def _service_model(service: AwsService) -> ServiceModel:
    model_name, api_version = SERVICE_MODELS[service]
    return ServiceModel(
        Loader().load_service_model(model_name, "service-2", api_version=api_version), service_name=model_name
    )


def _operation(service: AwsService, operation: str) -> OperationModel:
    return _service_model(service).operation_model(operation)


def make_session(secret_access_key: str, session_token: Optional[str]) -> requests.Session:
    redact = tuple(value for value in (secret_access_key, session_token) if value)
    return make_tracked_session(retry=NO_RETRY, redact_values=redact, allow_redirects=False)


def _error_from(parsed: dict[str, Any], status_code: int) -> AmazonCloudWatchError:
    error = parsed.get("Error") or {}
    code = str(error.get("Code") or "").split("#")[-1]
    # botocore reports an empty or HTML error body by its status number alone.
    if not code or code.isdigit():
        code = f"HTTP {status_code}"
    message = str(error.get("Message") or "")[:500]
    text = f"Amazon CloudWatch request failed: {code} - {message}"
    if code in THROTTLING_ERROR_CODES or status_code == 429:
        return AmazonCloudWatchThrottledError(text, code)
    if status_code >= 500:
        return AmazonCloudWatchTransientError(text, code)
    return AmazonCloudWatchError(text, code)


def _before_retry_wait(_state: RetryCallState) -> None:
    reach_safe_point()


def _retry_wait(seconds: float) -> None:
    interruptible_wait(seconds)


# The only retry layer: the session sends each try once, so tries and waits do not multiply.
@retry(
    retry=retry_if_exception_type((AmazonCloudWatchTransientError, requests.ConnectionError, requests.Timeout)),
    stop=stop_after_attempt(MAX_ATTEMPTS) | stop_before_delay(RETRY_BUDGET_SECONDS),
    wait=wait_exponential_jitter(initial=2, max=30),
    sleep=_retry_wait,
    before_sleep=_before_retry_wait,
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
    suffix = aws_dns_suffix(region)
    if suffix is None:
        raise ValueError(f"Unknown AWS region: {region}")
    url = f"https://{model.endpoint_prefix}.{region}.{suffix}{serialized['url_path']}"

    aws_request = AWSRequest(method="POST", url=url, data=body, headers=dict(serialized["headers"]))
    SigV4Auth(credentials, model.signing_name, region).add_auth(aws_request)

    response = session.post(url, data=body, headers=dict(aws_request.headers.items()), timeout=REQUEST_TIMEOUT)

    output_shape = operation_model.output_shape
    assert output_shape is not None  # every operation this source calls returns a body
    try:
        parsed = create_parser(model.protocol).parse(
            {"status_code": response.status_code, "headers": dict(response.headers), "body": response.content},
            output_shape,
        )
    except ResponseParserError:
        # A load balancer error page is not the protocol's format.
        parsed = {"Error": {}} if response.status_code >= 400 else {"Error": {"Message": "unreadable response"}}
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
    # A rejection without an error body reaches `_error_from` as its bare status.
    "HTTP 401": "AWS rejected the access key. Check the access key ID and secret access key, and that the key is still active.",
    "HTTP 403": "These AWS credentials cannot read CloudWatch. Grant logs:DescribeLogGroups, logs:FilterLogEvents, cloudwatch:DescribeAlarms, cloudwatch:DescribeAlarmHistory and cloudwatch:GetMetricData to the IAM user or role.",
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
    start_date: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """One `GetCallerIdentity` probe, plus a local check of the metric queries and start date.

    STS answers any valid key without an IAM permission, so a key scoped to metrics or alarms only
    still connects. A missing permission for a table surfaces when that table syncs."""
    if not aws_access_key_id or not aws_secret_access_key:
        return False, "AWS access key ID and secret access key are required"
    if not aws_region or not is_valid_region(aws_region):
        return False, "Enter an AWS region code, for example us-east-1."
    try:
        parse_metric_queries(metric_queries)
        parse_start_date(start_date)
    except ValueError as error:
        return False, str(error)

    try:
        send_operation(
            make_session(aws_secret_access_key, aws_session_token),
            Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None),
            aws_region.strip(),
            STS_SERVICE,
            "GetCallerIdentity",
            {},
        )
    except AmazonCloudWatchError as error:
        code = error.code or ""
        if code in VALIDATION_ERROR_MESSAGES:
            return False, VALIDATION_ERROR_MESSAGES[code]
        if isinstance(error, AmazonCloudWatchTransientError):
            return False, TRANSIENT_VALIDATION_ERROR
        capture_exception(error)
        return False, GENERIC_VALIDATION_ERROR
    except Exception:
        return False, "Could not reach Amazon CloudWatch. Check the region and try again."

    return True, None


def parse_start_date(value: Optional[str]) -> Optional[dt.datetime]:
    """The configured start date, or None when it is empty. A value that is not a date raises,
    because falling back to the default range would drop the history the user asked for."""
    if not value or not value.strip():
        return None
    parsed = coerce_datetime(value.strip())
    if parsed is None:
        raise ValueError(f"{INVALID_START_DATE}: enter it as YYYY-MM-DD, for example 2024-01-31.")
    return parsed


def resolve_window(
    endpoint_config: CloudWatchEndpointConfig,
    configured_start_date: Optional[str],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    now: dt.datetime,
) -> TimeWindow:
    """The time range this run asks AWS for: the watermark on an incremental run, else the start
    date, else the endpoint's default lookback. Never before the configured start date.

    The default lookback only bounds a first run. A run after a long pause starts at its watermark,
    so the gap is read, not dropped."""
    configured = parse_start_date(configured_start_date)
    start = configured or (now - dt.timedelta(days=endpoint_config.lookback_days or 0))
    if should_use_incremental_field:
        watermark = coerce_datetime(db_incremental_field_last_value)
        if watermark is not None:
            start = max(configured, watermark) if configured else watermark
    return TimeWindow(start=min(start, now), end=now)


# CloudWatch keeps datapoints at a coarser resolution as they age: 1-minute data for 15 days,
# 5-minute data for 63 days and 1-hour data for 455 days. A query asking for a finer period than
# the data still has returns nothing for that range.
_RESOLUTION_BY_AGE = (
    (dt.timedelta(days=63), 3600),
    (dt.timedelta(days=15), 300),
    (dt.timedelta(hours=3), 60),
)


def period_for_window(period: int, window_start: dt.datetime, now: dt.datetime) -> int:
    """The query period to use for a window: the requested one, rounded up to the coarsest
    resolution CloudWatch still keeps for the oldest data in the window."""
    age = now - window_start
    resolution = next((seconds for threshold, seconds in _RESOLUTION_BY_AGE if age > threshold), 1)
    if period % resolution == 0:
        return period
    return (period // resolution + 1) * resolution


def queries_for_window(
    queries: list[dict[str, Any]], window_start: dt.datetime, now: dt.datetime
) -> list[dict[str, Any]]:
    adapted = copy.deepcopy(queries)
    for query in adapted:
        if isinstance(query.get("MetricStat"), dict) and query["MetricStat"].get("Period"):
            query["MetricStat"]["Period"] = period_for_window(int(query["MetricStat"]["Period"]), window_start, now)
        elif query.get("Period"):
            query["Period"] = period_for_window(int(query["Period"]), window_start, now)
    return adapted


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

    def list_log_group_names(self, logger: FilteringBoundLogger, limit: int = MAX_DISCOVERED_LOG_GROUPS) -> list[str]:
        names: list[str] = []
        next_token: Optional[str] = None
        while len(names) < limit:
            params: dict[str, Any] = {"limit": min(LOG_GROUPS_PAGE_SIZE, limit - len(names))}
            if next_token:
                params["nextToken"] = next_token
            body = self.call(LOGS_SERVICE, "DescribeLogGroups", params)
            names.extend(
                group["logGroupName"]
                for group in body.get("logGroups") or []
                # FilterLogEvents reads Standard groups only; other classes would fail the whole table.
                if group.get("logGroupName") and group.get("logGroupClass", "STANDARD") == "STANDARD"
            )
            next_token = body.get("nextToken")
            if not next_token:
                return names
        logger.warning(
            f"Amazon CloudWatch has more than {limit} log groups, so only the first {limit} by name sync. "
            "List the log groups to sync on the source to choose them."
        )
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
    rows: list[dict[str, Any]] = []
    for item in body.get("AlarmHistoryItems") or []:
        row = _snake_keys(item)
        row["history_id"] = hashlib.sha256(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()
        rows.append(row)
    return rows


def check_metric_results(body: dict[str, Any]) -> None:
    """Raise for a query AWS answered with an error status inside an HTTP 200 response.

    `Forbidden` means the credentials cannot read that metric. `InternalError` is AWS's transient
    failure, retried with the attempt; the cursor of the page was not staged, so nothing is skipped.
    `PartialData` with no continuation token means the query produced more datapoints than one
    response holds, and the rest cannot be fetched.
    """
    for result in body.get("MetricDataResults") or []:
        status = result.get("StatusCode")
        if status == "PartialData" and not body.get("NextToken"):
            raise AmazonCloudWatchError(
                f"Amazon CloudWatch request failed: {METRIC_QUERY_PARTIAL_DATA} - metric query '{result.get('Id')}' "
                "returned more datapoints than one response holds",
                METRIC_QUERY_PARTIAL_DATA,
            )
        if status not in ("Forbidden", "InternalError"):
            continue
        detail = "; ".join(str(message.get("Value") or message.get("Code")) for message in result.get("Messages") or [])
        code = METRIC_QUERY_FORBIDDEN if status == "Forbidden" else METRIC_QUERY_INTERNAL_ERROR
        raise AmazonCloudWatchError(
            f"Amazon CloudWatch request failed: {code} - metric query '{result.get('Id')}': {detail}"[:600], code
        )


def metric_data_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in body.get("MetricDataResults") or []:
        timestamps = result.get("Timestamps") or []
        values = result.get("Values") or []
        for timestamp, value in zip(timestamps, values):
            rows.append(
                {
                    "query_id": result.get("Id"),
                    # One query returns several series for a SEARCH expression or a Metrics Insights
                    # GROUP BY. The label names the series, so it is part of the row key.
                    "label": result.get("Label") or result.get("Id"),
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
    logger: FilteringBoundLogger,
) -> list[tuple[str, Optional[str]]]:
    """The request series of one run: (slice key, log group) pairs for logs, window starts otherwise."""
    if endpoint_config.operation == "FilterLogEvents":
        groups = log_group_names or client.list_log_group_names(logger)
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
            "MetricDataQueries": queries_for_window(metric_queries, piece.start, window.end),
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

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    saved_start = coerce_datetime(resume.window_start) if resume else None
    saved_end = coerce_datetime(resume.window_end) if resume else None
    if saved_start is not None and saved_end is not None:
        window = TimeWindow(start=saved_start, end=saved_end)
    else:
        window = resolve_window(
            endpoint_config,
            start_date,
            should_use_incremental_field,
            db_incremental_field_last_value,
            dt.datetime.now(dt.UTC),
        )
    if resume is not None and resume.slice_key == COMPLETED_SLICE:
        resumable_source_manager.clear_state()
        return

    slices = _slices(endpoint_config, client, parse_log_group_names(log_group_names), window, logger)

    index, next_token = 0, None
    if resume is not None:
        # A saved slice that no longer exists (the window moved, a log group went away) restarts the run.
        for position, (slice_key, _) in enumerate(slices):
            if slice_key == resume.slice_key:
                index, next_token = position, resume.next_token
                logger.debug(f"Resuming Amazon CloudWatch sync. endpoint={endpoint}, slice={slice_key}")
                break

    for position in range(index, len(slices)):
        slice_key, log_group = slices[position]
        following_slice = slices[position + 1][0] if position + 1 < len(slices) else COMPLETED_SLICE
        while True:
            body = client.call(
                endpoint_config.service,
                endpoint_config.operation,
                _params(endpoint_config, slice_key, log_group, window, queries, next_token),
            )
            if endpoint_config.operation == "GetMetricData":
                check_metric_results(body)
            rows = _rows(endpoint_config, log_group, body)
            next_token = _next_token(endpoint_config, body)

            # Staged before the batch it covers: a crash after the write resumes at the next page,
            # or at the next slice once this one has no page left.
            resumable_source_manager.save_state(
                AmazonCloudWatchResumeConfig(
                    slice_key=slice_key if next_token else following_slice,
                    next_token=next_token,
                    window_start=window.start.isoformat(),
                    window_end=window.end.isoformat(),
                )
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
        sort_mode=endpoint_config.sort_mode,
    )
