import re
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_compute_optimizer.settings import (
    API_VERSION,
    DEFAULT_REGION,
    ENDPOINTS,
    ERROR_MESSAGES,
    PAGE_SIZE,
    TARGET_PREFIXES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awscomputeoptimizer import (
    AwsComputeOptimizerSourceConfig,
)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"POST"}),
    raise_on_status=False,
)


@frozen
class AwsComputeOptimizerResumeConfig:
    next_token: str | None = None
    complete: bool = False


class AwsComputeOptimizerError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"AWS Compute Optimizer request failed: {code}")


class AwsComputeOptimizerThrottleError(AwsComputeOptimizerError):
    pass


def error_for_response(response: requests.Response) -> AwsComputeOptimizerError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw_code = response.headers.get("x-amzn-ErrorType") or body.get("__type") or body.get("code")
    code = str(raw_code or f"HTTP {response.status_code}").split(":", 1)[0].rsplit("#", 1)[-1]
    # The transport retries HTTP statuses. AWS also returns throttling errors with HTTP 400.
    if response.status_code == 400 and code in {
        "ThrottlingException",
        "TooManyRequestsException",
        "RequestLimitExceeded",
    }:
        return AwsComputeOptimizerThrottleError(code)
    return AwsComputeOptimizerError(code)


class AwsComputeOptimizerClient:
    def __init__(self, config: AwsComputeOptimizerSourceConfig, api_version: str | None = None) -> None:
        version = api_version or API_VERSION
        if version not in TARGET_PREFIXES:
            raise ValueError("Unsupported AWS Compute Optimizer API version.")
        if not config.aws_access_key_id or not config.aws_secret_access_key:
            raise ValueError("Enter both an AWS access key ID and a secret access key.")
        self.region = config.region or DEFAULT_REGION
        if not re.fullmatch(r"(?:us|eu|ap|sa|ca|me|af|il|mx|cn)-(?:[a-z]+-)+[0-9]+", self.region):
            raise ValueError("Enter an AWS region, such as us-east-1.")
        suffix = "amazonaws.com.cn" if self.region.startswith("cn-") else "amazonaws.com"
        self.url = f"https://compute-optimizer.{self.region}.{suffix}/"
        self.target_prefix = TARGET_PREFIXES[version]
        self.signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            "compute-optimizer",
            self.region,
        )
        self.session = make_tracked_session(
            retry=TRANSPORT_RETRY,
            redact_values=tuple(
                value
                for value in (config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token)
                if value
            ),
        )

    def close(self) -> None:
        self.session.close()

    @retry(
        retry=retry_if_exception_type(AwsComputeOptimizerThrottleError),
        stop=stop_after_attempt(4),
        wait=wait_exponential_jitter(initial=1, max=10),
        reraise=True,
    )
    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = AWSRequest(
            method="POST",
            url=self.url,
            data=body,
            headers={
                "Content-Type": "application/x-amz-json-1.0",
                "X-Amz-Target": f"{self.target_prefix}.{operation}",
            },
        )
        self.signer.add_auth(request)
        response = self.session.post(
            self.url, data=body, headers=dict(request.headers), timeout=60, allow_redirects=False
        )
        if not 200 <= response.status_code < 300:
            raise error_for_response(response)
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("AWS Compute Optimizer returned an invalid response.")
        if result.get("errors"):
            error = result["errors"][0]
            raise AwsComputeOptimizerError(str(error.get("code") or "PartialResponseError"))
        return result


def normalize_row(item: dict[str, Any], region: str) -> dict[str, Any]:
    def flatten(obj: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        row: dict[str, Any] = {}
        for key, value in obj.items():
            column = prefix + _CAMEL_BOUNDARY.sub("_", key).lower()
            if isinstance(value, dict):
                row.update(flatten(value, column + "_"))
            else:
                row[column] = value
        return row

    row = flatten(item)
    timestamp = row.get("last_refresh_timestamp")
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        row["last_refresh_timestamp"] = datetime.fromtimestamp(timestamp, tz=UTC)
    row["region"] = region
    return row


def get_rows(
    config: AwsComputeOptimizerSourceConfig,
    endpoint: str,
    manager: ResumableSourceManager[AwsComputeOptimizerResumeConfig],
    api_version: str | None,
) -> Iterator[list[dict[str, Any]]]:
    settings = ENDPOINTS[endpoint]
    state = manager.load_state() or AwsComputeOptimizerResumeConfig()
    if state.complete:
        return
    token = state.next_token
    seen_tokens: set[str] = {token} if token else set()
    client = AwsComputeOptimizerClient(config, api_version)
    try:
        while True:
            payload: dict[str, Any] = {"maxResults": PAGE_SIZE}
            if token:
                payload["nextToken"] = token
            result = client.request(settings.operation, payload)
            rows = [normalize_row(item, client.region) for item in result.get(settings.result_key, [])]
            token = result.get("nextToken") or None
            if token is not None:
                if token in seen_tokens:
                    raise ValueError("AWS Compute Optimizer repeated a pagination token. Restart the sync.")
                seen_tokens.add(token)
            manager.save_state(AwsComputeOptimizerResumeConfig(next_token=token, complete=token is None))
            if rows:
                yield rows
            manager.safe_point()
            if token is None:
                return
    finally:
        client.close()


def validate_credentials(
    config: AwsComputeOptimizerSourceConfig, schema_name: str | None = None, api_version: str | None = None
) -> tuple[bool, str | None]:
    if schema_name is not None and schema_name not in ENDPOINTS:
        return False, "Unknown AWS Compute Optimizer table. Select a supported table."
    try:
        client = AwsComputeOptimizerClient(config, api_version)
    except ValueError as error:
        return False, str(error)
    operation = ENDPOINTS[schema_name].operation if schema_name is not None else "GetEnrollmentStatus"
    try:
        result = client.request(operation, {"maxResults": 1} if schema_name is not None else {})
        if schema_name is None and result.get("status") != "Active":
            return False, "Enable AWS Compute Optimizer for this account and wait until enrollment is active."
    except AwsComputeOptimizerError as error:
        if error.code in {"AccessDenied", "AccessDeniedException"}:
            if schema_name is None:
                return True, None
            return False, f"AWS denied access. Grant compute-optimizer:{operation} to the IAM user or role."
        return False, ERROR_MESSAGES.get(error.code, "Could not read AWS Compute Optimizer. Try again.")
    except (requests.RequestException, ValueError):
        return False, "Could not reach the AWS Compute Optimizer API. Try again."
    finally:
        client.close()
    return True, None


def aws_compute_optimizer_source(
    config: AwsComputeOptimizerSourceConfig,
    endpoint: str,
    manager: ResumableSourceManager[AwsComputeOptimizerResumeConfig],
    api_version: str | None = None,
) -> SourceResponse:
    if endpoint not in ENDPOINTS:
        raise ValueError("Unknown AWS Compute Optimizer table. Select a supported table.")
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(config, endpoint, manager, api_version),
        primary_keys=list(ENDPOINTS[endpoint].primary_keys),
        sort_mode=None,
        on_complete=manager.clear_state,
    )
