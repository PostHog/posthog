import re
import json
import time
import datetime as dt
from collections.abc import Iterator
from typing import Any

import requests
import structlog
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cloudtrail.settings import (
    ACCESS_DENIED_CODES,
    AWS_CLOUDTRAIL_ENDPOINTS,
    CREDENTIAL_ERRORS,
    INSIGHTS_METRIC_PERIOD_SECONDS,
    LOOKBACK_SECONDS,
    SKIPPED_PARENT_CODES,
    TARGET_PREFIXES,
    THROTTLE_CODES,
    CloudTrailEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

logger = structlog.get_logger(__name__)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["POST"]),
    raise_on_status=False,
)
# Minimum seconds between requests. LookupEvents and ListInsightsData allow two requests per second per account and
# region. ListInsightsMetricData allows one.
SPACED_OPERATIONS = {"LookupEvents": 0.5, "ListInsightsData": 0.5, "ListInsightsMetricData": 1.0}


@frozen
class AwsCloudTrailResumeConfig:
    next_token: str | None = None
    start_time: float | None = None
    end_time: float | None = None
    finished: bool = False
    # The fan-out parent of `next_token`. With no token, every row of this parent is already read.
    parent: str | None = None


class AwsCloudTrailError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(f"AWS CloudTrail request failed: {code}")
        self.code = code


class AwsCloudTrailThrottled(AwsCloudTrailError):
    pass


def error_for_response(response: requests.Response) -> AwsCloudTrailError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw_code = response.headers.get("x-amzn-ErrorType") or body.get("__type") or body.get("code")
    code = str(raw_code or f"HTTP {response.status_code}").split(":")[0].rsplit("#", 1)[-1]
    # The transport retries HTTP statuses. Only body-level throttles need a separate retry.
    if response.status_code == 400 and code in THROTTLE_CODES:
        return AwsCloudTrailThrottled(code)
    return AwsCloudTrailError(code)


class AwsCloudTrailClient:
    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        session_token: str | None,
        region: str,
        api_version: str,
    ) -> None:
        if not access_key_id or not secret_access_key:
            raise ValueError("Enter both an AWS access key ID and a secret access key.")
        if not re.fullmatch(r"(?:af|ap|ca|eu|il|me|mx|sa|us|cn)-(?:gov-)?[a-z]+-\d+", region):
            raise ValueError("Enter a valid AWS region, such as us-east-1.")
        if api_version not in TARGET_PREFIXES:
            raise ValueError(f"Unsupported AWS CloudTrail API version: {api_version}")
        self.region = region
        self.target_prefix = TARGET_PREFIXES[api_version]
        suffix = "amazonaws.com.cn" if region.startswith("cn-") else "amazonaws.com"
        self.url = f"https://cloudtrail.{region}.{suffix}/"
        self.signer = SigV4Auth(
            Credentials(access_key_id, secret_access_key, session_token or None), "cloudtrail", region
        )
        self.session = make_tracked_session(
            retry=TRANSPORT_RETRY,
            redact_values=tuple(value for value in (access_key_id, secret_access_key, session_token) if value),
        )
        self._last_request: dict[str, float] = {}

    @retry(
        retry=retry_if_exception_type(AwsCloudTrailThrottled),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation in SPACED_OPERATIONS:
            last = self._last_request.get(operation)
            if last is not None:
                time.sleep(max(0, SPACED_OPERATIONS[operation] - (time.monotonic() - last)))
            self._last_request[operation] = time.monotonic()
        body = json.dumps(payload).encode("utf-8")
        request = AWSRequest(
            method="POST",
            url=self.url,
            data=body,
            headers={
                "Content-Type": "application/x-amz-json-1.1",
                "X-Amz-Target": f"{self.target_prefix}.{operation}",
            },
        )
        self.signer.add_auth(request)
        response = self.session.post(
            self.url, data=body, headers=dict(request.headers), timeout=60, allow_redirects=False
        )
        if not 200 <= response.status_code < 300:
            raise error_for_response(response)
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise ValueError("AWS CloudTrail returned an invalid response.")
        return parsed

    def close(self) -> None:
        self.session.close()


def normalize_row(item: dict[str, Any], endpoint: CloudTrailEndpoint, region: str) -> dict[str, Any]:
    row = {_CAMEL_BOUNDARY.sub("_", key).lower(): value for key, value in item.items()}
    row["region"] = region
    for column in endpoint.timestamps:
        value = row.get(column)
        if isinstance(value, int | float) and not isinstance(value, bool):
            row[column] = dt.datetime.fromtimestamp(value, dt.UTC)
    return row


def request_payload(endpoint: CloudTrailEndpoint, page_size: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if endpoint.page_size is not None:
        payload["MaxResults"] = page_size or endpoint.page_size
    if endpoint.event_category is not None:
        payload["EventCategory"] = endpoint.event_category
    if endpoint.operation == "DescribeTrails":
        payload["includeShadowTrails"] = True
    return payload


def _epoch(value: dt.datetime | str | int | float) -> float:
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.UTC)
        return value.timestamp()
    return float(value)


def get_rows(
    client: AwsCloudTrailClient,
    endpoint: CloudTrailEndpoint,
    manager: ResumableSourceManager[AwsCloudTrailResumeConfig],
    last_value: dt.datetime | str | int | float | None,
) -> Iterator[list[dict[str, Any]]]:
    try:
        state = manager.load_state() or AwsCloudTrailResumeConfig()
        if state.finished:
            return
        start_time, end_time = state.start_time, state.end_time
        if endpoint.is_events and end_time is None:
            end_time = dt.datetime.now(dt.UTC).timestamp()
            if last_value is not None:
                start_time = max(_epoch(last_value), end_time - LOOKBACK_SECONDS)
        payload = request_payload(endpoint)
        if endpoint.is_events:
            payload["EndTime"] = end_time
            if start_time is not None:
                payload["StartTime"] = start_time
        next_token = state.next_token
        restarted = False
        while True:
            params = dict(payload)
            if next_token:
                params["NextToken"] = next_token
            try:
                body = client.request(endpoint.operation, params)
            except AwsCloudTrailError as error:
                if error.code == "InvalidNextTokenException" and state.next_token and not restarted:
                    next_token = None
                    restarted = True
                    continue
                raise
            next_token = body.get("NextToken") if endpoint.page_size is not None else None
            if next_token and next_token == params.get("NextToken"):
                raise ValueError("AWS CloudTrail returned a repeated page token.")
            rows = [normalize_row(item, endpoint, client.region) for item in body.get(endpoint.result_key, [])]
            manager.save_state(
                AwsCloudTrailResumeConfig(
                    next_token=next_token, start_time=start_time, end_time=end_time, finished=not next_token
                )
            )
            if rows:
                yield rows
            manager.safe_point()
            if not next_token:
                break
    finally:
        client.close()


@frozen
class FanOutParent:
    key: str
    payload: dict[str, Any]
    columns: dict[str, Any]


def _pages(
    client: AwsCloudTrailClient,
    operation: str,
    payload: dict[str, Any],
    manager: ResumableSourceManager[AwsCloudTrailResumeConfig],
) -> Iterator[dict[str, Any]]:
    next_token: str | None = None
    while True:
        params = {**payload, "NextToken": next_token} if next_token else dict(payload)
        body = client.request(operation, params)
        manager.safe_point()
        yield body
        next_token = body.get("NextToken")
        if next_token and next_token == params.get("NextToken"):
            raise ValueError("AWS CloudTrail returned a repeated page token.")
        if not next_token:
            return


def _skip_parent(error: AwsCloudTrailError, operation: str, parent: str) -> None:
    if error.code not in SKIPPED_PARENT_CODES:
        raise error
    logger.warning(
        "AWS CloudTrail skipped a parent it cannot read", operation=operation, parent=parent, code=error.code
    )


def _insights_trails(
    client: AwsCloudTrailClient, manager: ResumableSourceManager[AwsCloudTrailResumeConfig]
) -> list[str]:
    body = client.request("DescribeTrails", {"includeShadowTrails": True})
    manager.safe_point()
    return sorted(
        {
            trail["TrailARN"]
            for trail in body.get("trailList", [])
            if trail.get("HasInsightSelectors") and trail.get("TrailARN")
        }
    )


@frozen
class InsightSeries:
    trail_arn: str
    event_source: str
    event_name: str
    insight_type: str
    error_code: str


def _series(event: dict[str, Any], trail_arn: str) -> InsightSeries | None:
    try:
        details = json.loads(event.get("CloudTrailEvent") or "{}").get("insightDetails") or {}
    except (ValueError, AttributeError):
        return None
    event_source = details.get("eventSource") or event.get("EventSource")
    event_name = details.get("eventName") or event.get("EventName")
    insight_type = details.get("insightType")
    if not (event_source and event_name and insight_type):
        return None
    return InsightSeries(
        trail_arn=trail_arn,
        event_source=event_source,
        event_name=event_name,
        insight_type=insight_type,
        error_code=details.get("errorCode") or "",
    )


def insight_series_parents(
    client: AwsCloudTrailClient, manager: ResumableSourceManager[AwsCloudTrailResumeConfig]
) -> list[FanOutParent]:
    # Metrics exist only for activity that triggered an Insights event, so the events name every series.
    series: set[InsightSeries] = set()
    for body in _pages(client, "LookupEvents", {"MaxResults": 50, "EventCategory": "insight"}, manager):
        series.update(key for event in body.get("Events", []) if (key := _series(event, "")))
    for trail_arn in _insights_trails(client, manager):
        listing = {"InsightSource": trail_arn, "DataType": "InsightsEvents", "MaxResults": 50}
        try:
            for body in _pages(client, "ListInsightsData", listing, manager):
                series.update(key for event in body.get("Events", []) if (key := _series(event, trail_arn)))
        except AwsCloudTrailError as error:
            _skip_parent(error, "ListInsightsData", trail_arn)
    parents: list[FanOutParent] = []
    for item in series:
        payload: dict[str, Any] = {
            "EventSource": item.event_source,
            "EventName": item.event_name,
            "InsightType": item.insight_type,
            "Period": INSIGHTS_METRIC_PERIOD_SECONDS,
        }
        if item.error_code:
            payload["ErrorCode"] = item.error_code
        if item.trail_arn:
            payload["TrailName"] = item.trail_arn
        columns = {
            "trail_arn": item.trail_arn,
            "event_source": item.event_source,
            "event_name": item.event_name,
            "insight_type": item.insight_type,
            "error_code": item.error_code,
        }
        parents.append(FanOutParent(key=json.dumps(list(columns.values())), payload=payload, columns=columns))
    # A resumed run skips parents by comparing keys, so the walk follows key order.
    return sorted(parents, key=lambda parent: parent.key)


def fan_out_parents(
    client: AwsCloudTrailClient,
    endpoint: CloudTrailEndpoint,
    manager: ResumableSourceManager[AwsCloudTrailResumeConfig],
) -> list[FanOutParent]:
    if endpoint.parent == "trails":
        return [
            FanOutParent(
                key=arn, payload={"InsightSource": arn, "DataType": "InsightsEvents"}, columns={"trail_arn": arn}
            )
            for arn in _insights_trails(client, manager)
        ]
    if endpoint.parent == "event_data_stores":
        stores = {
            store["EventDataStoreArn"]
            for body in _pages(client, "ListEventDataStores", {"MaxResults": 100}, manager)
            for store in body.get("EventDataStores", [])
            if store.get("EventDataStoreArn")
        }
        return [
            FanOutParent(key=arn, payload={"EventDataStore": arn}, columns={"event_data_store_arn": arn})
            for arn in sorted(stores)
        ]
    if endpoint.parent == "insight_series":
        return insight_series_parents(client, manager)
    raise ValueError(f"Unknown AWS CloudTrail parent: {endpoint.parent}")


def _page_rows(
    body: dict[str, Any], endpoint: CloudTrailEndpoint, parent: FanOutParent, region: str
) -> list[dict[str, Any]]:
    if endpoint.operation == "ListInsightsMetricData":
        return [
            {
                "region": region,
                **parent.columns,
                "timestamp": dt.datetime.fromtimestamp(timestamp, dt.UTC),
                "value": value,
            }
            for timestamp, value in zip(body.get("Timestamps") or [], body.get("Values") or [], strict=False)
        ]
    return [{**normalize_row(item, endpoint, region), **parent.columns} for item in body.get(endpoint.result_key) or []]


def _describe_query(client: AwsCloudTrailClient, endpoint: CloudTrailEndpoint, row: dict[str, Any]) -> dict[str, Any]:
    try:
        details = client.request(
            "DescribeQuery", {"EventDataStore": row["event_data_store_arn"], "QueryId": row["query_id"]}
        )
    except AwsCloudTrailError as error:
        if error.code != "QueryIdNotFoundException":
            raise
        return row
    return {**row, **normalize_row(details, endpoint, client.region)}


def get_fan_out_rows(
    client: AwsCloudTrailClient,
    endpoint: CloudTrailEndpoint,
    manager: ResumableSourceManager[AwsCloudTrailResumeConfig],
    last_value: dt.datetime | str | int | float | None,
) -> Iterator[list[dict[str, Any]]]:
    try:
        state = manager.load_state() or AwsCloudTrailResumeConfig()
        if state.finished:
            return
        start_time, end_time = state.start_time, state.end_time
        if endpoint.retention_seconds is not None and end_time is None:
            end_time = dt.datetime.now(dt.UTC).timestamp()
            start_time = end_time - endpoint.retention_seconds
            if last_value is not None:
                start_time = max(start_time, _epoch(last_value) - endpoint.refresh_seconds)
        window = {} if end_time is None else {"StartTime": start_time, "EndTime": end_time}
        parents = fan_out_parents(client, endpoint, manager)
        for index, parent in enumerate(parents):
            if state.parent is not None and (
                parent.key < state.parent or (parent.key == state.parent and not state.next_token)
            ):
                continue
            resumed_token = state.next_token if parent.key == state.parent else None
            next_token = resumed_token
            try:
                while True:
                    params = {**request_payload(endpoint), **window, **parent.payload}
                    if next_token:
                        params["NextToken"] = next_token
                    try:
                        body = client.request(endpoint.operation, params)
                    except AwsCloudTrailError as error:
                        if error.code == "InvalidNextTokenException" and resumed_token and next_token == resumed_token:
                            next_token = resumed_token = None
                            continue
                        raise
                    next_token = body.get("NextToken")
                    if next_token and next_token == params.get("NextToken"):
                        raise ValueError("AWS CloudTrail returned a repeated page token.")
                    checkpoint = AwsCloudTrailResumeConfig(
                        next_token=next_token,
                        start_time=start_time,
                        end_time=end_time,
                        finished=not next_token and index == len(parents) - 1,
                        parent=parent.key,
                    )
                    rows = _page_rows(body, endpoint, parent, client.region)
                    if endpoint.operation != "ListQueries":
                        manager.save_state(checkpoint)
                        if rows:
                            yield rows
                    else:
                        # One describe call per row, so each row is handed over as soon as it is read. The cursor
                        # staged for the earlier rows still points at this page, so a hand-off reads it again.
                        for row in rows[:-1]:
                            yield [_describe_query(client, endpoint, row)]
                        last = [_describe_query(client, endpoint, rows[-1])] if rows else []
                        manager.save_state(checkpoint)
                        if last:
                            yield last
                    manager.safe_point()
                    if not next_token:
                        break
            except AwsCloudTrailError as error:
                _skip_parent(error, endpoint.operation, parent.key)
    finally:
        client.close()


def validate_credentials(
    access_key_id: str,
    secret_access_key: str,
    session_token: str | None,
    region: str,
    api_version: str,
    schema_name: str | None = None,
) -> tuple[bool, str | None]:
    endpoint = AWS_CLOUDTRAIL_ENDPOINTS.get(schema_name or "trails")
    if endpoint is None:
        return False, f"Unknown AWS CloudTrail table: {schema_name}"
    permissions = endpoint.permissions or (endpoint.operation,)
    if endpoint.probe is not None:
        endpoint = AWS_CLOUDTRAIL_ENDPOINTS[endpoint.probe]
    try:
        client = AwsCloudTrailClient(access_key_id, secret_access_key, session_token, region, api_version)
    except ValueError as error:
        return False, str(error)
    try:
        client.request(endpoint.operation, request_payload(endpoint, page_size=1))
    except AwsCloudTrailError as error:
        if error.code in ACCESS_DENIED_CODES:
            if schema_name is None:
                return True, None
            if len(permissions) == 1:
                return False, f"Grant the cloudtrail:{permissions[0]} IAM permission to read this table."
            granted = ", ".join(f"cloudtrail:{permission}" for permission in permissions)
            return False, f"Grant the {granted} IAM permissions to read this table."
        return False, CREDENTIAL_ERRORS.get(error.code, "Could not read from AWS CloudTrail. Try again.")
    except (requests.RequestException, ValueError):
        return False, "Could not reach the AWS CloudTrail API. Check the selected region and try again."
    finally:
        client.close()
    return True, None


def aws_cloudtrail_source(
    access_key_id: str,
    secret_access_key: str,
    session_token: str | None,
    region: str,
    api_version: str,
    endpoint_name: str,
    manager: ResumableSourceManager[AwsCloudTrailResumeConfig],
    last_value: dt.datetime | str | int | float | None,
) -> SourceResponse:
    endpoint = AWS_CLOUDTRAIL_ENDPOINTS.get(endpoint_name)
    if endpoint is None:
        raise ValueError(f"Unknown AWS CloudTrail table: {endpoint_name}")
    rows = get_rows if endpoint.parent is None else get_fan_out_rows
    return SourceResponse(
        name=endpoint_name,
        items=lambda: rows(
            AwsCloudTrailClient(access_key_id, secret_access_key, session_token, region, api_version),
            endpoint,
            manager,
            last_value,
        ),
        primary_keys=list(endpoint.primary_key),
        # Event lookups return newest first, and fan-out tables keep an order only within one parent.
        sort_mode="desc" if endpoint.incremental_field else None,
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        on_complete=manager.clear_state,
    )
