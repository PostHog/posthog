import re
import json
import datetime as dt
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_config.settings import (
    AWS_CONFIG_ENDPOINTS,
    ERROR_MESSAGES,
    TARGET_PREFIXES,
    AwsConfigEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsconfig import (
        AwsConfigSourceConfig,
    )

_REGION = re.compile(r"[a-z]{2}(?:-[a-z]+)+-\d+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_THROTTLE_CODES = {"Throttling", "ThrottlingException", "TooManyRequestsException", "RequestLimitExceeded"}
_TIMESTAMP_COLUMNS = {"configuration_item_capture_time", "resource_creation_time", "last_update_requested_time"}

# Config reads use POST, so the transport must retry this method for transient HTTP failures.
TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"POST"}),
    raise_on_status=False,
)


@frozen
class AwsConfigResumeConfig:
    next_token: str | None = None
    complete: bool = False


class AwsConfigError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"AWS Config request failed: {code} - {message}")
        self.code = code


class AwsConfigThrottledError(AwsConfigError):
    pass


def error_for_response(response: requests.Response) -> AwsConfigError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw_code = response.headers.get("x-amzn-ErrorType") or body.get("__type") or body.get("code")
    code = str(raw_code or f"HTTP {response.status_code}").split(":", 1)[0].rsplit("#", 1)[-1]
    message = str(body.get("message") or body.get("Message") or response.text)[:500]
    # HTTP retries belong to the tracked transport. Only body-level throttles need another retry policy.
    error_class = AwsConfigThrottledError if response.status_code == 400 and code in _THROTTLE_CODES else AwsConfigError
    return error_class(code, message)


class AwsConfigClient:
    def __init__(self, config: "AwsConfigSourceConfig", api_version: str) -> None:
        if not config.aws_access_key_id or not config.aws_secret_access_key:
            raise ValueError("Enter both an AWS access key ID and a secret access key.")
        self.region = config.region or "us-east-1"
        if not _REGION.fullmatch(self.region):
            raise ValueError("Enter an AWS region such as us-east-1.")
        if api_version not in TARGET_PREFIXES:
            raise ValueError(f"Unsupported AWS Config API version: {api_version}")
        self.target_prefix = TARGET_PREFIXES[api_version]
        suffix = "amazonaws.com.cn" if self.region.startswith("cn-") else "amazonaws.com"
        self.url = f"https://config.{self.region}.{suffix}/"
        self._signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            "config",
            self.region,
        )
        self._session = make_tracked_session(
            retry=TRANSPORT_RETRY,
            redact_values=tuple(value for value in (config.aws_secret_access_key, config.aws_session_token) if value),
        )

    def close(self) -> None:
        self._session.close()

    @retry(
        retry=retry_if_exception_type(AwsConfigThrottledError),
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
            headers={
                "Content-Type": "application/x-amz-json-1.1",
                "X-Amz-Target": f"{self.target_prefix}.{operation}",
            },
        )
        self._signer.add_auth(request)
        response = self._session.post(
            self.url, data=body, headers=dict(request.headers), timeout=60, allow_redirects=False
        )
        if response.status_code != 200:
            raise error_for_response(response)
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise ValueError("AWS Config returned an invalid response. Try the sync again.")
        return parsed


def request_payload(endpoint: AwsConfigEndpoint, *, probe: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if endpoint.page_size is not None:
        payload["Limit"] = 1 if probe else endpoint.page_size
    if endpoint.expression is not None:
        payload["Expression"] = endpoint.expression
    return payload


def normalize_row(item: dict[str, Any], region: str) -> dict[str, Any]:
    row = {_CAMEL_BOUNDARY.sub("_", key).lower(): value for key, value in item.items()}
    row["region"] = region
    for key in _TIMESTAMP_COLUMNS & row.keys():
        value = row[key]
        if isinstance(value, int | float) and not isinstance(value, bool):
            row[key] = dt.datetime.fromtimestamp(value, tz=dt.UTC)
        elif isinstance(value, str) and value:
            row[key] = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return row


def get_rows(
    config: "AwsConfigSourceConfig",
    endpoint: AwsConfigEndpoint,
    api_version: str,
    manager: "ResumableSourceManager[AwsConfigResumeConfig]",
) -> Generator[list[dict[str, Any]]]:
    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None and resume.complete:
        manager.clear_state()
        return
    next_token = resume.next_token if resume else None
    restarting = next_token is not None
    client = AwsConfigClient(config, api_version)
    try:
        while True:
            payload = request_payload(endpoint)
            if next_token:
                payload["NextToken"] = next_token
            try:
                body = client.request(endpoint.operation, payload)
            except AwsConfigError as error:
                if restarting and error.code == "InvalidNextTokenException":
                    # A fresh retry must restart the full-refresh destination as well as extraction.
                    manager.clear_state()
                raise
            restarting = False
            rows = []
            for item in body.get(endpoint.result_key) or []:
                if endpoint.expression is not None:
                    item = json.loads(item)
                if not isinstance(item, dict):
                    raise ValueError("AWS Config returned an invalid resource. Try the sync again.")
                rows.append(normalize_row(item, client.region))
            token = body.get("NextToken") or None
            if token is not None and (not isinstance(token, str) or token == next_token):
                raise ValueError("AWS Config returned an invalid page token. Try the sync again.")
            next_token = token
            manager.save_state(AwsConfigResumeConfig(next_token=next_token, complete=next_token is None))
            if rows:
                yield rows
            manager.safe_point()
            if next_token is None:
                break
        manager.clear_state()
    finally:
        client.close()


def validate_credentials(
    config: "AwsConfigSourceConfig", api_version: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    endpoint = AWS_CONFIG_ENDPOINTS.get(schema_name or "config_rules")
    if endpoint is None:
        return False, f"Unknown AWS Config table: {schema_name}"
    try:
        client = AwsConfigClient(config, api_version)
    except ValueError as error:
        return False, str(error)
    try:
        client.request(endpoint.operation, request_payload(endpoint, probe=True))
    except AwsConfigError as error:
        if error.code in {"AccessDenied", "AccessDeniedException"}:
            if schema_name is None:
                return True, None
            return False, f"Grant config:{endpoint.operation} to this IAM user or role to sync this table."
        return False, ERROR_MESSAGES.get(error.code, "Could not read AWS Config. Check the region and try again.")
    except (requests.RequestException, ValueError):
        return False, "Could not reach the AWS Config API. Check the region and try again."
    finally:
        client.close()
    return True, None


def aws_config_source(
    config: "AwsConfigSourceConfig",
    endpoint: str,
    api_version: str,
    manager: "ResumableSourceManager[AwsConfigResumeConfig]",
) -> SourceResponse:
    endpoint_config = AWS_CONFIG_ENDPOINTS.get(endpoint)
    if endpoint_config is None:
        raise ValueError(f"Unknown AWS Config table: {endpoint}")
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(config, endpoint_config, api_version, manager),
        primary_keys=list(endpoint_config.primary_key),
        sort_mode=None,
    )
