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
    SageMakerEndpoint,
    SageMakerParent,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import probe_status_message
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
    "HyperParameterTuningEndTime",
    "EndTime",
    "StartTime",
    "ScheduledTime",
    "TransformStartTime",
    "TransformEndTime",
}


@frozen
class AwsSagemakerResumeConfig:
    next_token: str | None = None
    watermark: float | None = None
    complete: bool = False
    parent_name: str | None = None


class AwsSagemakerError(Exception):
    def __init__(self, code: str, status_code: int | None = None) -> None:
        self.code = code
        self.status_code = status_code
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
        return AwsSagemakerThrottledError(code, response.status_code)
    return AwsSagemakerError(code, response.status_code)


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


def parent_names(
    client: AwsSagemakerClient,
    parent: SageMakerParent,
    manager: ResumableSourceManager[AwsSagemakerResumeConfig],
) -> list[str]:
    names: list[str] = []
    token: str | None = None
    while True:
        payload: dict[str, Any] = {"MaxResults": MAX_RESULTS, "SortBy": "Name", "SortOrder": "Ascending"}
        if token:
            payload["NextToken"] = token
        page = client.request(parent.list_operation, payload)
        names.extend(item[parent.name_field] for item in page[parent.result_key])
        manager.safe_point()
        next_token = page.get("NextToken") or None
        if next_token is None:
            break
        if next_token == token:
            raise ValueError("AWS SageMaker returned a repeated pagination token.")
        token = next_token
    # Sorting here keeps the resume order independent of how AWS collates names.
    return sorted(set(names))


def list_pages(
    client: AwsSagemakerClient,
    settings: SageMakerEndpoint,
    manager: ResumableSourceManager[AwsSagemakerResumeConfig],
    watermark: float | None,
    incremental: bool,
    token: str | None,
    parent_name: str | None = None,
    following_parent: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    while True:
        payload: dict[str, Any] = {
            "MaxResults": MAX_RESULTS,
            "SortBy": "CreationTime",
            "SortOrder": "Ascending",
            **dict(settings.list_filters),
        }
        if settings.parent and parent_name:
            payload[settings.parent.name_field] = parent_name
        if watermark is not None and incremental and settings.incremental:
            payload["CreationTimeAfter"] = watermark
        if token:
            payload["NextToken"] = token
        page = client.request(settings.list_operation, payload)
        next_token = page.get("NextToken") or None
        if next_token == token and next_token is not None:
            raise ValueError("AWS SageMaker returned a repeated pagination token.")
        describe_operation = settings.describe_operation
        rows = [
            normalize_row(
                client.request(describe_operation, settings.describe_payload(item)) if describe_operation else item
            )
            for item in page[settings.result_key]
        ]
        for row in rows:
            if any(not row.get(key) for key in settings.primary_keys):
                raise ValueError("AWS SageMaker returned a resource without its identifier.")
        manager.save_state(
            AwsSagemakerResumeConfig(
                next_token=next_token,
                watermark=watermark,
                complete=next_token is None and following_parent is None,
                parent_name=parent_name if next_token else following_parent,
            )
        )
        if rows:
            yield rows
        manager.safe_point()
        if next_token is None:
            break
        token = next_token


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
        if settings.parent is None:
            yield from list_pages(client, settings, manager, watermark, incremental, token)
            return
        start = state.parent_name if state else None
        parents = [name for name in parent_names(client, settings.parent, manager) if start is None or name >= start]
        for index, name in enumerate(parents):
            following = parents[index + 1] if index + 1 < len(parents) else None
            try:
                yield from list_pages(
                    client,
                    settings,
                    manager,
                    watermark,
                    incremental,
                    token if name == start else None,
                    parent_name=name,
                    following_parent=following,
                )
            except AwsSagemakerError as error:
                # A parent deleted during the walk must not stop the walk over the remaining parents.
                if error.code != "ResourceNotFound":
                    raise
                manager.save_state(
                    AwsSagemakerResumeConfig(watermark=watermark, complete=following is None, parent_name=following)
                )
                manager.safe_point()
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
        filters = dict(settings.list_filters)
        if settings.parent:
            parents = client.request(settings.parent.list_operation, {"MaxResults": 1})[settings.parent.result_key]
            if not parents:
                return True, None
            filters[settings.parent.name_field] = parents[0][settings.parent.name_field]
        page = client.request(settings.list_operation, {"MaxResults": 1, **filters})
        if schema_name and settings.describe_operation and page.get(settings.result_key):
            client.request(settings.describe_operation, settings.describe_payload(page[settings.result_key][0]))
    except AwsSagemakerError as error:
        if error.code in {"AccessDenied", "AccessDeniedException"}:
            if schema_name is None:
                return True, None
            operations = [
                settings.parent.list_operation if settings.parent else None,
                settings.list_operation,
                settings.describe_operation,
            ]
            permissions = ", ".join(f"sagemaker:{operation}" for operation in operations if operation)
            return False, f"Grant these permissions for this table: {permissions}."
        for code, message in ERROR_MESSAGES.items():
            if error.code.startswith(code):
                return False, message
        status_message = probe_status_message("AWS SageMaker", error.status_code)
        if status_message:
            return False, status_message
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
        primary_keys=list(settings.primary_keys),
        partition_keys=["creation_time"],
        partition_mode="datetime",
        partition_format="month",
        sort_mode="asc" if settings.incremental else None,
    )
