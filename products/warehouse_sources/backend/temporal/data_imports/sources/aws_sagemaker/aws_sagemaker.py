import re
import json
import datetime as dt
from collections.abc import Iterator
from typing import Any

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_sagemaker.settings import (
    ENDPOINTS,
    MAX_RESULTS,
    TARGET_PREFIXES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssagemaker import (
    AwsSagemakerSourceConfig,
)

TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["POST"]),
    raise_on_status=False,
)
THROTTLE_CODES = {"ThrottlingException", "Throttling", "TooManyRequestsException", "RequestLimitExceeded"}
ERROR_MESSAGES = {
    "AccessDenied": "AWS denied access. Grant the SageMaker list and describe permissions for the selected tables.",
    "UnrecognizedClientException": "AWS rejected the credentials. Check the access key ID, secret access key, and session token.",
    "InvalidClientTokenId": "AWS rejected the access key. Enter an active access key ID and secret access key.",
    "InvalidSignatureException": "AWS rejected the signature. Check the secret access key and session token.",
    "SignatureDoesNotMatch": "AWS rejected the signature. Check the secret access key and selected region.",
    "ExpiredToken": "The AWS session token expired. Reconnect with new credentials.",
    "SubscriptionRequiredException": "Enable SageMaker for this AWS account and region, then try again.",
    "OptInRequired": "Enable SageMaker for this AWS account and region, then try again.",
}
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_TIMESTAMP_FIELDS = {
    "CreationTime",
    "LastModifiedTime",
    "TrainingStartTime",
    "TrainingEndTime",
    "ProcessingStartTime",
    "ProcessingEndTime",
}


@frozen
class AwsSagemakerResumeConfig:
    next_token: str | None = None
    watermark: float | None = None
    complete: bool = False


class AwsSagemakerError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"AWS SageMaker request failed: {code}")


class AwsSagemakerThrottledError(AwsSagemakerError):
    pass


def endpoint_url(region: str) -> str:
    if not re.fullmatch(r"(?:af|ap|ca|cn|eu|il|me|mx|sa|us)(?:-gov)?-[a-z]+-\d+", region):
        raise ValueError("Enter an AWS region, such as us-east-1.")
    suffix = "amazonaws.com.cn" if region.startswith("cn-") else "amazonaws.com"
    return f"https://api.sagemaker.{region}.{suffix}/"


def error_for_response(response: requests.Response) -> AwsSagemakerError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw_code = response.headers.get("x-amzn-ErrorType") or body.get("__type") or body.get("code")
    code = str(raw_code or f"HTTP {response.status_code}").split(":")[0].split("#")[-1]
    # Only body-level throttles need another retry layer; the transport retries 429 and 5xx.
    if response.status_code == 400 and code in THROTTLE_CODES:
        return AwsSagemakerThrottledError(code)
    return AwsSagemakerError(code)


class AwsSagemakerClient:
    def __init__(self, config: AwsSagemakerSourceConfig, api_version: str) -> None:
        if not config.aws_access_key_id or not config.aws_secret_access_key:
            raise ValueError("Enter both an AWS access key ID and a secret access key.")
        if api_version not in TARGET_PREFIXES:
            raise ValueError(f"Unsupported SageMaker API version: {api_version}")
        self.url = endpoint_url(config.region)
        self.target_prefix = TARGET_PREFIXES[api_version]
        self.signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            "sagemaker",
            config.region,
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
        retry=retry_if_exception_type(AwsSagemakerThrottledError),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = AWSRequest(
            method="POST",
            url=self.url,
            data=body,
            headers={"Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": f"{self.target_prefix}.{operation}"},
        )
        self.signer.add_auth(request)
        response = self.session.post(
            self.url, data=body, headers=dict(request.headers), timeout=60, allow_redirects=False
        )
        if response.status_code >= 300:
            raise error_for_response(response)
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise ValueError("AWS SageMaker returned an invalid response.")
        return parsed


def normalize_row(item: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in item.items():
        if key == "ResponseMetadata":
            continue
        if key in _TIMESTAMP_FIELDS and isinstance(value, int | float) and not isinstance(value, bool):
            value = dt.datetime.fromtimestamp(value, tz=dt.UTC)
        row[_CAMEL_BOUNDARY.sub("_", key).lower()] = value
    return row


def timestamp(value: dt.datetime | str | int | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)).timestamp()


def get_rows(
    config: AwsSagemakerSourceConfig,
    endpoint: str,
    api_version: str,
    manager: ResumableSourceManager[AwsSagemakerResumeConfig],
    incremental: bool,
    last_value: dt.datetime | str | int | float | None,
) -> Iterator[list[dict[str, Any]]]:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    state = manager.load_state()
    if state and state.complete:
        return
    watermark = state.watermark if state else timestamp(last_value) if incremental and settings.incremental else None
    token = state.next_token if state else None
    client = AwsSagemakerClient(config, api_version)
    try:
        while True:
            payload: dict[str, Any] = {"MaxResults": MAX_RESULTS, "SortBy": "CreationTime", "SortOrder": "Ascending"}
            if watermark is not None and incremental and settings.incremental:
                payload["CreationTimeAfter"] = watermark
            if token:
                payload["NextToken"] = token
            page = client.request(settings.list_operation, payload)
            next_token = page.get("NextToken") or None
            if next_token == token and next_token is not None:
                raise ValueError("AWS SageMaker returned a repeated pagination token.")
            rows = [
                normalize_row(
                    client.request(settings.describe_operation, {settings.name_field: item[settings.name_field]})
                )
                for item in page[settings.result_key]
            ]
            for row in rows:
                if not row.get(settings.primary_key):
                    raise ValueError("AWS SageMaker returned a resource without its ARN.")
            manager.save_state(
                AwsSagemakerResumeConfig(next_token=next_token, watermark=watermark, complete=next_token is None)
            )
            if rows:
                yield rows
            manager.safe_point()
            if next_token is None:
                break
            token = next_token
    finally:
        client.close()


def validate_credentials(
    config: AwsSagemakerSourceConfig, schema_name: str | None, api_version: str
) -> tuple[bool, str | None]:
    if schema_name is not None and schema_name not in ENDPOINTS:
        return False, f"Unknown SageMaker table: {schema_name}"
    settings = ENDPOINTS[schema_name or "models"]
    try:
        client = AwsSagemakerClient(config, api_version)
    except ValueError as error:
        return False, str(error)
    try:
        page = client.request(settings.list_operation, {"MaxResults": 1})
        if schema_name and page.get(settings.result_key):
            item = page[settings.result_key][0]
            client.request(settings.describe_operation, {settings.name_field: item[settings.name_field]})
    except AwsSagemakerError as error:
        if error.code in {"AccessDenied", "AccessDeniedException"}:
            if schema_name is None:
                return True, None
            return (
                False,
                f"Grant sagemaker:{settings.list_operation} and sagemaker:{settings.describe_operation} for this table.",
            )
        for code, message in ERROR_MESSAGES.items():
            if error.code.startswith(code):
                return False, message
        raise
    except requests.RequestException:
        return False, "Could not reach AWS SageMaker. Check the region and try again."
    finally:
        client.close()
    return True, None


def aws_sagemaker_source(
    config: AwsSagemakerSourceConfig,
    endpoint: str,
    api_version: str,
    manager: ResumableSourceManager[AwsSagemakerResumeConfig],
    incremental: bool,
    last_value: dt.datetime | str | int | float | None,
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(config, endpoint, api_version, manager, incremental, last_value),
        primary_keys=[settings.primary_key],
        partition_keys=["creation_time"],
        partition_mode="datetime",
        partition_format="month",
        sort_mode="asc" if settings.incremental else None,
    )
