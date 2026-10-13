import re
import json
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.exceptions import InvalidHeader
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_waf.settings import (
    ACCESS_DENIED_CODES,
    AWS_WAF_ENDPOINTS,
    ERROR_MESSAGES,
    PAGE_SIZE,
    TARGET_PREFIX,
    WAF_API_VERSION,
    WafEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awswaf import AwsWafSourceConfig

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@frozen
class AwsWafResumeConfig:
    next_marker: str | None = None


class AwsWafError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"AWS WAF request failed: {code} - {message}")
        self.code = code


class AwsWafRetryableError(AwsWafError):
    def __init__(self, code: str, message: str, retry_after: float = 0) -> None:
        super().__init__(code, message)
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
        return AwsWafRetryableError(code, message, retry_after)
    return AwsWafError(code, message)


def retry_wait(state: RetryCallState) -> float:
    error = state.outcome.exception() if state.outcome else None
    delay = wait_exponential_jitter(initial=1, max=60)(state)
    return max(delay, error.retry_after) if isinstance(error, AwsWafRetryableError) else delay


class AwsWafClient:
    def __init__(self, config: AwsWafSourceConfig, api_version: str = WAF_API_VERSION) -> None:
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
        self.url = f"https://wafv2.{self.region}.{suffix}/"
        self.signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            "wafv2",
            self.region,
        )
        # WAF can throttle with HTTP 400, so one retry layer handles both HTTP statuses and AWS error codes.
        self.session = make_tracked_session(
            retry=Retry(total=0),
            redact_values=tuple(value for value in (config.aws_secret_access_key, config.aws_session_token) if value),
        )

    def close(self) -> None:
        self.session.close()

    @retry(
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
            headers={"Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": f"{TARGET_PREFIX}.{operation}"},
        )
        self.signer.add_auth(request)
        response = self.session.post(
            self.url, data=body, headers=dict(request.headers), timeout=60, allow_redirects=False
        )
        if response.status_code != 200:
            raise error_for_response(response)
        return response.json()

    def get_resource(self, endpoint: WafEndpoint, summary: dict[str, Any]) -> dict[str, Any]:
        result = self.request(
            endpoint.get_operation, {"Scope": self.scope, "Id": summary["Id"], "Name": summary["Name"]}
        )
        resource = result[endpoint.object_key]
        row = {
            re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", key).lower(): value
            for key, value in resource.items()
        }
        row["region"] = self.region
        row["scope"] = self.scope
        return row


def validate_credentials(
    config: AwsWafSourceConfig, schema_name: str | None = None, api_version: str = WAF_API_VERSION
) -> tuple[bool, str | None]:
    endpoint = AWS_WAF_ENDPOINTS.get(schema_name or "web_acls")
    if endpoint is None:
        return False, f"Unknown AWS WAF table: {schema_name}"
    try:
        client = AwsWafClient(config, api_version)
    except ValueError as error:
        return False, str(error)
    try:
        result = client.request(endpoint.list_operation, {"Scope": client.scope, "Limit": 1})
        if schema_name and result[endpoint.list_key]:
            client.get_resource(endpoint, result[endpoint.list_key][0])
    except AwsWafError as error:
        if error.code in ACCESS_DENIED_CODES:
            if schema_name is None:
                return True, None
            return False, f"Grant wafv2:{endpoint.list_operation} and wafv2:{endpoint.get_operation} for this table."
        if error.code in ERROR_MESSAGES:
            return False, ERROR_MESSAGES[error.code]
        raise
    finally:
        client.close()
    return True, None


def get_rows(
    config: AwsWafSourceConfig,
    endpoint: WafEndpoint,
    manager: "ResumableSourceManager[AwsWafResumeConfig]",
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    state = manager.load_state() or AwsWafResumeConfig()
    client = AwsWafClient(config, api_version)
    marker = state.next_marker
    try:
        while True:
            payload: dict[str, Any] = {"Scope": client.scope, "Limit": PAGE_SIZE}
            if marker:
                payload["NextMarker"] = marker
            result = client.request(endpoint.list_operation, payload)
            rows = []
            for summary in result[endpoint.list_key]:
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


def aws_waf_source(
    config: AwsWafSourceConfig,
    endpoint: str,
    manager: "ResumableSourceManager[AwsWafResumeConfig]",
    api_version: str = WAF_API_VERSION,
) -> SourceResponse:
    if endpoint not in AWS_WAF_ENDPOINTS:
        raise ValueError(f"Unknown AWS WAF table: {endpoint}")
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(config, AWS_WAF_ENDPOINTS[endpoint], manager, api_version),
        primary_keys=["arn"],
        sort_mode=None,
        on_complete=manager.clear_state,
    )
