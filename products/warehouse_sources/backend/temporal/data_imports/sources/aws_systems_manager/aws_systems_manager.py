import re
import json
import datetime as dt
from collections.abc import Iterator
from typing import Any

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.serialize import create_serializer
from botocore.session import get_session
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_systems_manager.settings import (
    API_VERSION,
    ENDPOINTS,
    ERROR_MESSAGES,
    SystemsManagerEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssystemsmanager import (
    AwsSystemsManagerSourceConfig,
)

TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"POST"}),
    raise_on_status=False,
)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


@frozen
class SystemsManagerResumeConfig:
    next_token: str | None = None
    completed: bool = False


class SystemsManagerError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"AWS Systems Manager request failed: {code} - {message}")


class SystemsManagerThrottledError(SystemsManagerError):
    pass


def error_for_response(response: requests.Response) -> SystemsManagerError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw_code = response.headers.get("x-amzn-ErrorType") or body.get("__type") or body.get("code")
    code = str(raw_code or f"HTTP {response.status_code}").split(":")[0].rsplit("#", 1)[-1]
    message = str(body.get("Message") or body.get("message") or response.text)[:500]
    # The HTTP transport cannot detect throttling encoded in a 400 response.
    if response.status_code == 400 and code in {"Throttling", "ThrottlingException", "TooManyRequestsException"}:
        return SystemsManagerThrottledError(code, message)
    return SystemsManagerError(code, message)


class SystemsManagerClient:
    def __init__(self, config: AwsSystemsManagerSourceConfig, api_version: str) -> None:
        if api_version != API_VERSION:
            raise ValueError(f"Unsupported AWS Systems Manager API version: {api_version}")
        if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", config.aws_region):
            raise ValueError("Enter a valid AWS region, such as us-east-1.")
        session = get_session()
        self._model = session.get_service_model("ssm", api_version=api_version)
        self._serializer = create_serializer(self._model.metadata["protocol"])
        endpoint = session.get_component("endpoint_resolver").construct_endpoint("ssm", config.aws_region)
        if endpoint is None:
            raise ValueError("AWS Systems Manager is unavailable in this region. Select another region.")
        self.url = f"https://{endpoint['hostname']}/"
        self.region = config.aws_region
        self._signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            "ssm",
            self.region,
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

    @retry(
        retry=retry_if_exception_type(SystemsManagerThrottledError),
        stop=stop_after_attempt(6),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        serialized = self._serializer.serialize_to_request(payload, self._model.operation_model(operation))
        request = AWSRequest(method="POST", url=self.url, data=serialized["body"], headers=serialized["headers"])
        self._signer.add_auth(request)
        response = self._session.post(
            self.url, data=serialized["body"], headers=dict(request.headers), timeout=60, allow_redirects=False
        )
        if response.status_code >= 400:
            raise error_for_response(response)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("AWS Systems Manager returned an invalid response.")
        return body


def request_payload(endpoint: SystemsManagerEndpoint, *, probe: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"MaxResults": endpoint.probe_size if probe else endpoint.page_size}
    if endpoint.operation == "GetInventory":
        payload["ResultAttributes"] = [{"TypeName": "AWS:InstanceInformation"}]
    return payload


def _flatten(obj: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in obj.items():
        column = prefix + _CAMEL_BOUNDARY.sub("_", key).lower()
        if key == "Data" and not prefix:
            # Inventory type names and content keys are dynamic, so retain them in one JSON column.
            row[column] = json.dumps(value)
        elif isinstance(value, dict):
            row.update(_flatten(value, column + "_"))
        else:
            row[column] = value
    return row


def normalize_row(item: dict[str, Any], endpoint: SystemsManagerEndpoint, region: str) -> dict[str, Any]:
    row = _flatten(item)
    row["region"] = region
    for name in endpoint.timestamps:
        value = row.get(name)
        if isinstance(value, int | float) and not isinstance(value, bool):
            row[name] = dt.datetime.fromtimestamp(value, tz=dt.UTC)
    return row


def get_rows(
    config: AwsSystemsManagerSourceConfig,
    endpoint: SystemsManagerEndpoint,
    api_version: str,
    manager: ResumableSourceManager[SystemsManagerResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    state = manager.load_state() if manager.can_resume() else None
    if state and state.completed:
        return
    next_token = state.next_token if state else None
    resumed = bool(next_token)
    client = SystemsManagerClient(config, api_version)
    try:
        while True:
            payload = request_payload(endpoint)
            if next_token:
                payload["NextToken"] = next_token
            try:
                body = client.request(endpoint.operation, payload)
            except SystemsManagerError as error:
                if resumed and error.code == "InvalidNextToken":
                    next_token = None
                    resumed = False
                    continue
                raise
            resumed = False
            rows = [normalize_row(item, endpoint, client.region) for item in body.get(endpoint.result_key, [])]
            token = body.get("NextToken") or None
            if token is not None and (not isinstance(token, str) or token == next_token):
                raise ValueError("AWS Systems Manager returned an invalid or repeated page token.")
            next_token = token
            manager.save_state(SystemsManagerResumeConfig(next_token=next_token, completed=next_token is None))
            if rows:
                yield rows
            manager.safe_point()
            if next_token is None:
                return
    finally:
        client.close()


def validate_credentials(
    config: AwsSystemsManagerSourceConfig, api_version: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    if not config.aws_access_key_id or not config.aws_secret_access_key:
        return False, "Enter both an AWS access key ID and a secret access key."
    endpoint = ENDPOINTS.get(schema_name or "managed_instances")
    if endpoint is None:
        return False, f"Unknown AWS Systems Manager table: {schema_name}"
    try:
        client = SystemsManagerClient(config, api_version)
    except ValueError as error:
        return False, str(error)
    try:
        client.request(endpoint.operation, request_payload(endpoint, probe=True))
    except SystemsManagerError as error:
        if error.code in {"AccessDenied", "AccessDeniedException"}:
            if schema_name is None:
                return True, None
            return False, f"Grant ssm:{endpoint.operation} to read this table."
        return False, ERROR_MESSAGES.get(
            error.code, "AWS Systems Manager could not validate the credentials. Try again."
        )
    except requests.RequestException:
        return False, "Could not reach AWS Systems Manager. Check the region and try again."
    finally:
        client.close()
    return True, None


def aws_systems_manager_source(
    config: AwsSystemsManagerSourceConfig,
    schema_name: str,
    api_version: str,
    manager: ResumableSourceManager[SystemsManagerResumeConfig],
) -> SourceResponse:
    endpoint = ENDPOINTS.get(schema_name)
    if endpoint is None:
        raise ValueError(f"Unknown AWS Systems Manager table: {schema_name}")
    return SourceResponse(
        name=schema_name,
        items=lambda: get_rows(config, endpoint, api_version, manager),
        primary_keys=list(endpoint.primary_key),
        sort_mode=None,
        on_complete=manager.clear_state,
    )
