import re
import json
import hashlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from tenacity import RetryCallState, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.exceptions import InvalidHeader
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_waf.settings import (
    ACCESS_DENIED_CODES,
    AWS_WAF_ENDPOINTS,
    CLOUDWATCH_SERVICE,
    ERROR_MESSAGES,
    LIST_CALLS,
    MANAGED_RULE_GROUPS,
    METRICS_HISTORY,
    METRICS_NAMESPACE,
    METRICS_PER_REQUEST,
    METRICS_PERIOD_SECONDS,
    PAGE_SIZE,
    PRIMARY_KEYS,
    PROTECTED_RESOURCE_TYPES,
    REDACTED_HEADERS,
    REQUEST_METRICS,
    SAMPLED_REQUESTS,
    SAMPLED_REQUESTS_MAX_ITEMS,
    SAMPLED_REQUESTS_WINDOW,
    TABLE_PERMISSIONS,
    WAF_API_VERSION,
    WAFV2_SERVICE,
    WEB_ACL_RESOURCES,
    AwsService,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import probe_status_message
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awswaf import AwsWafSourceConfig

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@frozen
class AwsWafResumeConfig:
    next_marker: str | None = None


class AwsWafError(Exception):
    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        super().__init__(f"AWS WAF request failed: {code} - {message}")
        self.code = code
        self.status_code = status_code


class AwsWafRetryableError(AwsWafError):
    def __init__(self, code: str, message: str, retry_after: float = 0, status_code: int | None = None) -> None:
        super().__init__(code, message, status_code)
        self.retry_after = retry_after


def error_for_response(response: requests.Response) -> AwsWafError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw_code = response.headers.get("x-amzn-ErrorType") or body.get("__type") or body.get("code")
    code = str(raw_code or f"HTTP {response.status_code}").split(":")[0].rsplit("#", 1)[-1]
    message = str(body.get("message") or body.get("Message") or "AWS could not complete the request.")[:500]
    if (
        response.status_code == 429
        or response.status_code >= 500
        or (response.status_code == 400 and code in {"ThrottlingException", "Throttling", "RequestLimitExceeded"})
    ):
        retry_after = 0.0
        if header := response.headers.get("Retry-After"):
            try:
                retry_after = min(Retry().parse_retry_after(header), 60)
            except InvalidHeader:
                pass
        return AwsWafRetryableError(code, message, retry_after, response.status_code)
    return AwsWafError(code, message, response.status_code)


def retry_wait(state: RetryCallState) -> float:
    error = state.outcome.exception() if state.outcome else None
    delay = wait_exponential_jitter(initial=1, max=60)(state)
    return max(delay, error.retry_after) if isinstance(error, AwsWafRetryableError) else delay


def utc_now() -> datetime:
    return datetime.now(UTC)


def snake_keys(data: dict[str, Any]) -> dict[str, Any]:
    return {
        re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", key).lower(): value
        for key, value in data.items()
    }


def from_epoch(value: Any) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if isinstance(value, int | float) else None


class AwsWafClient:
    def __init__(
        self,
        config: AwsWafSourceConfig,
        api_version: str = WAF_API_VERSION,
        service: AwsService = WAFV2_SERVICE,
        capture: bool = True,
    ) -> None:
        if api_version != WAF_API_VERSION:
            raise ValueError(f"Unsupported AWS WAF API version: {api_version}")
        if not config.aws_access_key_id or not config.aws_secret_access_key:
            raise ValueError("Enter both an AWS access key ID and a secret access key.")
        if config.scope not in {"REGIONAL", "CLOUDFRONT"}:
            raise ValueError("Select REGIONAL or CLOUDFRONT for the AWS WAF scope.")
        if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", config.aws_region):
            raise ValueError("Enter an AWS region name, such as us-east-1.")
        self.scope = config.scope
        self.region = "us-east-1" if self.scope == "CLOUDFRONT" else config.aws_region
        suffix = "amazonaws.com.cn" if self.region.startswith("cn-") else "amazonaws.com"
        self.service = service
        self.url = f"https://{service.signing_name}.{self.region}.{suffix}/"
        self.signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            service.signing_name,
            self.region,
        )
        # WAF can throttle with HTTP 400, so one retry layer handles both HTTP statuses and AWS error codes.
        self.session = make_tracked_session(
            retry=Retry(total=0),
            capture=capture,
            redact_values=tuple(value for value in (config.aws_secret_access_key, config.aws_session_token) if value),
        )

    def close(self) -> None:
        self.session.close()

    @retry_with_deadline(
        retry=retry_if_exception_type((AwsWafRetryableError, requests.ConnectionError, requests.Timeout)),
        stop=stop_after_attempt(5),
        wait=retry_wait,
        reraise=True,
    )
    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = AWSRequest(
            method="POST",
            url=self.url,
            data=body,
            headers={
                "Content-Type": self.service.content_type,
                "X-Amz-Target": f"{self.service.target_prefix}.{operation}",
            },
        )
        self.signer.add_auth(request)
        response = self.session.post(
            self.url, data=body, headers=dict(request.headers), timeout=60, allow_redirects=False
        )
        if response.status_code != 200:
            raise error_for_response(response)
        return response.json()

    def with_location(self, row: dict[str, Any]) -> dict[str, Any]:
        row["region"] = self.region
        row["scope"] = self.scope
        return row

    def get_resource(self, endpoint: str, summary: dict[str, Any]) -> dict[str, Any]:
        if endpoint == MANAGED_RULE_GROUPS:
            result = self.request(
                "DescribeManagedRuleGroup",
                {"Scope": self.scope, "VendorName": summary["VendorName"], "Name": summary["Name"]},
            )
            return self.with_location({**snake_keys(summary), **snake_keys(result)})
        waf_endpoint = AWS_WAF_ENDPOINTS[endpoint]
        result = self.request(
            waf_endpoint.get_operation, {"Scope": self.scope, "Id": summary["Id"], "Name": summary["Name"]}
        )
        return self.with_location(snake_keys(result[waf_endpoint.object_key]))

    def get_web_acl(self, summary: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return self.request("GetWebACL", {"Scope": self.scope, "Id": summary["Id"], "Name": summary["Name"]})[
                "WebACL"
            ]
        except AwsWafError as error:
            if error.code != "WAFNonexistentItemException":
                raise
            return None

    def list_resources(self, web_acl_arn: str, resource_type: str) -> list[str]:
        try:
            result = self.request("ListResourcesForWebACL", {"WebACLArn": web_acl_arn, "ResourceType": resource_type})
        except AwsWafError as error:
            # Some resource types are not offered in every region, and AWS rejects them as invalid parameters.
            if error.code not in {"WAFNonexistentItemException", "WAFInvalidParameterException"}:
                raise
            return []
        return result.get("ResourceArns") or []

    def get_sampled_requests(
        self, web_acl_arn: str, metric_name: str, start: datetime, end: datetime, max_items: int
    ) -> dict[str, Any]:
        try:
            return self.request(
                "GetSampledRequests",
                {
                    "WebAclArn": web_acl_arn,
                    "RuleMetricName": metric_name,
                    "Scope": self.scope,
                    "TimeWindow": {"StartTime": start.timestamp(), "EndTime": end.timestamp()},
                    "MaxItems": max_items,
                },
            )
        except AwsWafError as error:
            if error.code != "WAFNonexistentItemException":
                raise
            return {}


def validate_credentials(
    config: AwsWafSourceConfig, schema_name: str | None = None, api_version: str = WAF_API_VERSION
) -> tuple[bool, str | None]:
    table = schema_name or "web_acls"
    if table not in TABLE_PERMISSIONS:
        return False, f"Unknown AWS WAF table: {schema_name}"
    try:
        # Sampled requests carry end-user headers, so they stay out of HTTP sample capture.
        client = AwsWafClient(config, api_version, capture=table != SAMPLED_REQUESTS)
    except ValueError as error:
        return False, str(error)
    try:
        if schema_name is None:
            client.request("ListWebACLs", {"Scope": client.scope, "Limit": 1})
        else:
            probe_table(client, config, table, api_version)
    except AwsWafError as error:
        if error.code in ACCESS_DENIED_CODES:
            if schema_name is None:
                return True, None
            *others, last = TABLE_PERMISSIONS[table]
            return False, f"Grant {', '.join(others)} and {last} for this table."
        if error.code in ERROR_MESSAGES:
            return False, ERROR_MESSAGES[error.code]
        status_message = probe_status_message("AWS WAF", error.status_code)
        if status_message:
            return False, status_message
        raise
    finally:
        client.close()
    return True, None


def sampled_metric_names(web_acl: dict[str, Any]) -> list[str]:
    rules = [
        *(web_acl.get("PreProcessFirewallManagerRuleGroups") or []),
        *(web_acl.get("Rules") or []),
        *(web_acl.get("PostProcessFirewallManagerRuleGroups") or []),
    ]
    names = [
        rule["VisibilityConfig"]["MetricName"]
        for rule in rules
        if rule.get("VisibilityConfig", {}).get("SampledRequestsEnabled")
    ]
    return list(dict.fromkeys(names))


def probe_table(client: AwsWafClient, config: AwsWafSourceConfig, table: str, api_version: str) -> None:
    if table == REQUEST_METRICS:
        metrics_client = AwsWafClient(config, api_version, CLOUDWATCH_SERVICE)
        try:
            metrics_client.request("ListMetrics", {"Namespace": METRICS_NAMESPACE})
        finally:
            metrics_client.close()
        return
    list_call = LIST_CALLS.get(table, LIST_CALLS["web_acls"])
    summaries = client.request(list_call.operation, {"Scope": client.scope, "Limit": 1})[list_call.key]
    if not summaries:
        return
    if table == WEB_ACL_RESOURCES:
        if client.scope == "REGIONAL":
            client.list_resources(summaries[0]["ARN"], PROTECTED_RESOURCE_TYPES[0])
    elif table == SAMPLED_REQUESTS:
        web_acl = client.get_web_acl(summaries[0])
        if web_acl and (names := sampled_metric_names(web_acl)):
            end = utc_now()
            client.get_sampled_requests(web_acl["ARN"], names[0], end - SAMPLED_REQUESTS_WINDOW, end, 1)
    else:
        client.get_resource(table, summaries[0])


def iter_web_acls(
    client: AwsWafClient,
    manager: "ResumableSourceManager[AwsWafResumeConfig]",
    rows_for_web_acl: Callable[[dict[str, Any]], Iterator[list[dict[str, Any]]]],
) -> Iterator[list[dict[str, Any]]]:
    """Yield the rows of every web ACL.

    The marker of the current page stays staged until the next page is read, so a resumed run reads that page again.
    """
    state = manager.load_state() or AwsWafResumeConfig()
    marker = state.next_marker
    while True:
        payload: dict[str, Any] = {"Scope": client.scope, "Limit": PAGE_SIZE}
        if marker:
            payload["NextMarker"] = marker
        result = client.request("ListWebACLs", payload)
        next_marker = result.get("NextMarker") or None
        if next_marker and next_marker == marker:
            raise ValueError("AWS WAF returned a repeated pagination marker.")
        manager.save_state(AwsWafResumeConfig(next_marker=marker))
        for web_acl in result["WebACLs"]:
            yield from rows_for_web_acl(web_acl)
        manager.safe_point()
        if next_marker is None:
            return
        marker = next_marker


def get_rows(
    config: AwsWafSourceConfig,
    endpoint: str,
    manager: "ResumableSourceManager[AwsWafResumeConfig]",
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    state = manager.load_state() or AwsWafResumeConfig()
    client = AwsWafClient(config, api_version)
    marker = state.next_marker
    list_call = LIST_CALLS[endpoint]
    try:
        while True:
            payload: dict[str, Any] = {"Scope": client.scope, "Limit": PAGE_SIZE}
            if marker:
                payload["NextMarker"] = marker
            result = client.request(list_call.operation, payload)
            rows = []
            for summary in result[list_call.key]:
                try:
                    rows.append(client.get_resource(endpoint, summary))
                except AwsWafError as error:
                    if error.code != "WAFNonexistentItemException":
                        raise
            next_marker = result.get("NextMarker") or None
            if next_marker and next_marker == marker:
                raise ValueError("AWS WAF returned a repeated pagination marker.")
            manager.save_state(AwsWafResumeConfig(next_marker=next_marker))
            if rows:
                yield rows
            manager.safe_point()
            if next_marker is None:
                break
            marker = next_marker
    finally:
        client.close()


def protected_resource_rows(
    client: AwsWafClient, manager: "ResumableSourceManager[AwsWafResumeConfig]", web_acl: dict[str, Any]
) -> Iterator[list[dict[str, Any]]]:
    for resource_type in PROTECTED_RESOURCE_TYPES:
        rows = [
            client.with_location(
                {
                    "web_acl_arn": web_acl["ARN"],
                    "web_acl_id": web_acl["Id"],
                    "web_acl_name": web_acl["Name"],
                    "resource_type": resource_type,
                    "resource_arn": resource_arn,
                }
            )
            for resource_arn in client.list_resources(web_acl["ARN"], resource_type)
        ]
        if rows:
            yield rows
        else:
            manager.safe_point()


def get_web_acl_resource_rows(
    config: AwsWafSourceConfig, manager: "ResumableSourceManager[AwsWafResumeConfig]", api_version: str
) -> Iterator[list[dict[str, Any]]]:
    client = AwsWafClient(config, api_version)
    try:
        # CloudFront distributions are listed by the CloudFront API, not by ListResourcesForWebACL.
        if client.scope != "REGIONAL":
            return
        yield from iter_web_acls(client, manager, lambda web_acl: protected_resource_rows(client, manager, web_acl))
    finally:
        client.close()


def sampled_request_row(
    client: AwsWafClient, web_acl: dict[str, Any], metric_name: str, sample: dict[str, Any], population_size: Any
) -> dict[str, Any]:
    request = dict(sample.get("Request") or {})
    request["Headers"] = [
        {**header, "Value": "[REDACTED]"} if str(header.get("Name", "")).lower() in REDACTED_HEADERS else header
        for header in request.get("Headers") or []
    ]
    sample = {**sample, "Request": request}
    digest = hashlib.sha256(
        json.dumps([web_acl["ARN"], metric_name, sample], sort_keys=True, default=str).encode()
    ).hexdigest()
    row = {
        "id": digest,
        "web_acl_arn": web_acl["ARN"],
        "web_acl_name": web_acl["Name"],
        "rule_metric_name": metric_name,
        **snake_keys(request),
        **snake_keys({key: value for key, value in sample.items() if key != "Request"}),
        "population_size": population_size,
    }
    row["timestamp"] = from_epoch(sample.get("Timestamp"))
    return client.with_location(row)


def sampled_rows_for_web_acl(
    client: AwsWafClient,
    manager: "ResumableSourceManager[AwsWafResumeConfig]",
    summary: dict[str, Any],
    start: datetime,
    end: datetime,
) -> Iterator[list[dict[str, Any]]]:
    web_acl = client.get_web_acl(summary)
    manager.safe_point()
    if web_acl is None:
        return
    for metric_name in sampled_metric_names(web_acl):
        window_start = start
        while window_start < end:
            result = client.get_sampled_requests(
                web_acl["ARN"], metric_name, window_start, end, SAMPLED_REQUESTS_MAX_ITEMS
            )
            rows = [
                sampled_request_row(client, web_acl, metric_name, sample, result.get("PopulationSize"))
                for sample in result.get("SampledRequests") or []
            ]
            if rows:
                yield rows
            else:
                manager.safe_point()
            # AWS ends the returned window early when the rule saw 5,000 requests before the requested end.
            returned_end = from_epoch((result.get("TimeWindow") or {}).get("EndTime"))
            if returned_end is None or returned_end <= window_start or returned_end >= end:
                break
            window_start = returned_end


def get_sampled_request_rows(
    config: AwsWafSourceConfig,
    manager: "ResumableSourceManager[AwsWafResumeConfig]",
    api_version: str,
    last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    end = utc_now()
    start = end - SAMPLED_REQUESTS_WINDOW
    watermark = parse_datetime_value(last_value)
    if watermark and watermark > start:
        start = watermark
    if start >= end:
        return
    client = AwsWafClient(config, api_version, capture=False)
    try:
        yield from iter_web_acls(
            client, manager, lambda summary: sampled_rows_for_web_acl(client, manager, summary, start, end)
        )
    finally:
        client.close()


def metric_id(metric: dict[str, Any]) -> str:
    dimensions = sorted(f"{dimension['Name']}={dimension['Value']}" for dimension in metric.get("Dimensions") or [])
    return "|".join([metric["MetricName"], *dimensions])


def get_request_metric_rows(
    config: AwsWafSourceConfig,
    manager: "ResumableSourceManager[AwsWafResumeConfig]",
    api_version: str,
    last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    end = utc_now()
    start = max(parse_datetime_value(last_value) or end - METRICS_HISTORY, end - METRICS_HISTORY)
    start = start.replace(minute=0, second=0, microsecond=0)
    client = AwsWafClient(config, api_version, CLOUDWATCH_SERVICE)
    try:
        metrics: list[dict[str, Any]] = []
        list_payload: dict[str, Any] = {"Namespace": METRICS_NAMESPACE}
        if client.scope == "REGIONAL":
            list_payload["Dimensions"] = [{"Name": "Region", "Value": client.region}]
        while True:
            result = client.request("ListMetrics", list_payload)
            for metric in result.get("Metrics") or []:
                dimension_names = {dimension["Name"] for dimension in metric.get("Dimensions") or []}
                # CloudFront metrics have no Region dimension, regional metrics always have one.
                if (client.scope == "REGIONAL") == ("Region" in dimension_names):
                    metrics.append(metric)
            manager.safe_point()
            next_token = result.get("NextToken")
            if not next_token:
                break
            list_payload["NextToken"] = next_token

        for offset in range(0, len(metrics), METRICS_PER_REQUEST):
            batch = {f"m{index}": metric for index, metric in enumerate(metrics[offset : offset + METRICS_PER_REQUEST])}
            payload: dict[str, Any] = {
                "MetricDataQueries": [
                    {
                        "Id": query_id,
                        "MetricStat": {"Metric": metric, "Period": METRICS_PERIOD_SECONDS, "Stat": "Sum"},
                        "ReturnData": True,
                    }
                    for query_id, metric in batch.items()
                ],
                "StartTime": start.timestamp(),
                "EndTime": end.timestamp(),
                "ScanBy": "TimestampAscending",
            }
            while True:
                result = client.request("GetMetricData", payload)
                rows = []
                for data in result.get("MetricDataResults") or []:
                    metric = batch[data["Id"]]
                    # A failed series still returns HTTP 200, and skipping it would let the watermark pass its gap.
                    if data.get("StatusCode") not in (None, "Complete", "PartialData"):
                        raise AwsWafRetryableError(
                            str(data["StatusCode"]), f"CloudWatch could not return {metric_id(metric)}."
                        )
                    dimensions = {dimension["Name"]: dimension["Value"] for dimension in metric.get("Dimensions") or []}
                    for timestamp, value in zip(data.get("Timestamps") or [], data.get("Values") or []):
                        rows.append(
                            client.with_location(
                                {
                                    "metric_id": metric_id(metric),
                                    "metric_name": metric["MetricName"],
                                    "dimensions": dimensions,
                                    "web_acl": dimensions.get("WebACL"),
                                    "rule": dimensions.get("Rule"),
                                    "timestamp": from_epoch(timestamp),
                                    "value": value,
                                }
                            )
                        )
                if rows:
                    yield rows
                else:
                    manager.safe_point()
                next_token = result.get("NextToken")
                if not next_token:
                    break
                payload["NextToken"] = next_token
    finally:
        client.close()


def iter_rows(
    config: AwsWafSourceConfig,
    endpoint: str,
    manager: "ResumableSourceManager[AwsWafResumeConfig]",
    api_version: str,
    incremental_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    if endpoint == WEB_ACL_RESOURCES:
        return get_web_acl_resource_rows(config, manager, api_version)
    if endpoint == SAMPLED_REQUESTS:
        return get_sampled_request_rows(config, manager, api_version, incremental_last_value)
    if endpoint == REQUEST_METRICS:
        return get_request_metric_rows(config, manager, api_version, incremental_last_value)
    return get_rows(config, endpoint, manager, api_version)


def aws_waf_source(
    config: AwsWafSourceConfig,
    endpoint: str,
    manager: "ResumableSourceManager[AwsWafResumeConfig]",
    api_version: str = WAF_API_VERSION,
    incremental_last_value: Any = None,
) -> SourceResponse:
    if endpoint not in PRIMARY_KEYS:
        raise ValueError(f"Unknown AWS WAF table: {endpoint}")
    return SourceResponse(
        name=endpoint,
        items=lambda: iter_rows(config, endpoint, manager, api_version, incremental_last_value),
        primary_keys=PRIMARY_KEYS[endpoint],
        sort_mode=None,
        on_complete=manager.clear_state,
    )
