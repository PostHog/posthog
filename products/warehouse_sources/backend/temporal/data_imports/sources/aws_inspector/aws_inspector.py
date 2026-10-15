import re
import json
import datetime as dt
from collections.abc import Iterator
from typing import Any

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_inspector.settings import (
    AWS_INSPECTOR_ENDPOINTS,
    ERROR_MESSAGES,
    INSPECTOR_API_VERSION,
    AwsInspectorEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsinspector import (
    AwsInspectorSourceConfig,
)

TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["POST"]),
    raise_on_status=False,
)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


@frozen
class AwsInspectorResumeConfig:
    next_token: str | None = None
    updated_after: float | None = None
    completed: bool = False


class AwsInspectorError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"AWS Inspector request failed: {code} - {message}")
        self.code = code
        self.message = message


def error_for_response(response: requests.Response) -> AwsInspectorError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw_code = response.headers.get("x-amzn-ErrorType") or body.get("__type") or body.get("code")
    code = str(raw_code or f"HTTP {response.status_code}").split(":")[0].split("#")[-1]
    message = str(body.get("message") or body.get("Message") or response.reason or "")[:500]
    if response.status_code in (400, 403) and any(
        phrase in message.lower() for phrase in ("not subscribed", "not enabled", "subscription is required")
    ):
        code = "SubscriptionRequiredException"
    return AwsInspectorError(code, message)


def error_message(error: AwsInspectorError) -> str | None:
    return next((message for code, message in ERROR_MESSAGES.items() if error.code.startswith(code)), None)


class AwsInspectorClient:
    def __init__(self, config: AwsInspectorSourceConfig, api_version: str = INSPECTOR_API_VERSION) -> None:
        if api_version != INSPECTOR_API_VERSION:
            raise ValueError(f"Unsupported AWS Inspector API version: {api_version}")
        if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", config.region):
            raise ValueError("Enter an AWS region code, such as us-east-1.")
        if not config.aws_access_key_id or not config.aws_secret_access_key:
            raise ValueError("Enter both an AWS access key ID and a secret access key.")
        suffix = "amazonaws.com.cn" if config.region.startswith("cn-") else "amazonaws.com"
        self._base_url = f"https://inspector2.{config.region}.{suffix}"
        self._signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            "inspector2",
            config.region,
        )
        self._session = make_tracked_session(
            retry=TRANSPORT_RETRY,
            redact_values=tuple(
                value
                for value in (config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token)
                if value
            ),
        )

    def close(self) -> None:
        self._session.close()

    def request(self, endpoint: AwsInspectorEndpoint, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        url = self._base_url + endpoint.path
        request = AWSRequest(method="POST", url=url, data=body, headers={"Content-Type": "application/json"})
        self._signer.add_auth(request)
        response = self._session.post(url, data=body, headers=dict(request.headers), timeout=60, allow_redirects=False)
        if response.status_code != 200:
            raise error_for_response(response)
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise ValueError("AWS Inspector returned an invalid response.")
        return parsed


def timestamp(value: dt.datetime | str | int | float) -> float:
    if isinstance(value, int | float):
        return float(value)
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.timestamp()


def request_payload(endpoint: AwsInspectorEndpoint, updated_after: float | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if endpoint.page_size is not None:
        payload["maxResults"] = endpoint.page_size
    if endpoint.operation == "ListCoverageStatistics":
        payload["groupBy"] = "RESOURCE_TYPE"
    if endpoint.operation == "ListFindings" and updated_after is not None:
        payload["filterCriteria"] = {"updatedAt": [{"startInclusive": updated_after}]}
    return payload


def normalize_row(endpoint: AwsInspectorEndpoint, item: dict[str, Any], region: str) -> dict[str, Any]:
    row = {_CAMEL_BOUNDARY.sub("_", key).lower(): value for key, value in item.items()}
    for column in endpoint.timestamp_columns:
        if row.get(column) is not None:
            row[column] = dt.datetime.fromtimestamp(timestamp(row[column]), tz=dt.UTC)
    row["region"] = region
    return row


def get_rows(
    config: AwsInspectorSourceConfig,
    endpoint: AwsInspectorEndpoint,
    manager: ResumableSourceManager[AwsInspectorResumeConfig],
    updated_after: float | None,
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    state = manager.load_state() if manager.can_resume() else None
    if state is not None and state.completed:
        return
    next_token = state.next_token if state else None
    payload = request_payload(endpoint, state.updated_after if state else updated_after)
    client = AwsInspectorClient(config, api_version)
    try:
        while True:
            request_body = dict(payload)
            if next_token:
                request_body["nextToken"] = next_token
            body = client.request(endpoint, request_body)
            rows = [normalize_row(endpoint, item, config.region) for item in body.get(endpoint.result_key, [])]
            token = body.get("nextToken") or None
            if token is not None and (not isinstance(token, str) or token == next_token):
                raise ValueError("AWS Inspector returned an invalid pagination token.")
            manager.save_state(
                AwsInspectorResumeConfig(
                    next_token=token,
                    updated_after=state.updated_after if state else updated_after,
                    completed=token is None,
                )
            )
            if rows:
                yield rows
            manager.safe_point()
            if token is None:
                break
            next_token = token
    finally:
        client.close()


def validate_credentials(
    config: AwsInspectorSourceConfig,
    schema_name: str | None = None,
    api_version: str = INSPECTOR_API_VERSION,
) -> tuple[bool, str | None]:
    endpoint = AWS_INSPECTOR_ENDPOINTS.get(schema_name or "findings")
    if endpoint is None:
        return False, f"Unknown AWS Inspector table: {schema_name}"
    try:
        client = AwsInspectorClient(config, api_version)
    except ValueError as error:
        return False, str(error)
    payload = request_payload(endpoint)
    if endpoint.page_size is not None:
        payload["maxResults"] = 1
    try:
        client.request(endpoint, payload)
    except AwsInspectorError as error:
        if error.code.startswith("AccessDenied") or error.code == "HTTP 403":
            if schema_name is None:
                return True, None
            return False, f"Grant inspector2:{endpoint.operation} to read this table."
        message = error_message(error)
        if message:
            return False, message
        raise
    finally:
        client.close()
    return True, None


def aws_inspector_source(
    config: AwsInspectorSourceConfig,
    endpoint: str,
    manager: ResumableSourceManager[AwsInspectorResumeConfig],
    should_use_incremental_field: bool,
    last_value: dt.datetime | str | int | float | None,
    api_version: str = INSPECTOR_API_VERSION,
) -> SourceResponse:
    endpoint_config = AWS_INSPECTOR_ENDPOINTS.get(endpoint)
    if endpoint_config is None:
        raise ValueError(f"Unknown AWS Inspector table: {endpoint}")
    updated_after = (
        timestamp(last_value)
        if endpoint == "findings" and should_use_incremental_field and last_value is not None
        else None
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(config, endpoint_config, manager, updated_after, api_version),
        primary_keys=list(endpoint_config.primary_keys),
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        # Inspector filters by updatedAt but cannot sort by it.
        # "desc" saves the watermark once at job end, so unordered rows cannot strand older ones.
        sort_mode="desc",
        on_complete=manager.clear_state,
    )
