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
_TIMESTAMP_COLUMNS = {
    "configuration_item_capture_time",
    "resource_creation_time",
    "last_update_requested_time",
    "last_updated_time",
    "result_recorded_time",
    "config_rule_invoked_time",
    "ordering_timestamp",
    "configuration_item_delivery_time",
    "invocation_time",
    "evaluation_start_timestamp",
}

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
    # Fan-out tables: the parent page to fetch again, and the parent that `next_token` continues.
    parent_next_token: str | None = None
    parent_key: str | None = None
    # Incremental start time of the interrupted attempt, because page tokens belong to the original filter.
    since: float | None = None


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


def request_payload(endpoint: AwsConfigEndpoint, *, probe: bool = False, since: float | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = dict(endpoint.params or {})
    if endpoint.page_size is not None:
        payload[endpoint.limit_key] = 1 if probe else endpoint.page_size
    if endpoint.expression is not None:
        payload["Expression"] = endpoint.expression
    if since is not None and endpoint.incremental_filter:
        *parents, leaf = endpoint.incremental_filter
        target = payload
        for key in parents:
            target = target.setdefault(key, {})
        target[leaf] = since
    return payload


def epoch_seconds(value: Any) -> float:
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, dt.datetime):
        return (value if value.tzinfo else value.replace(tzinfo=dt.UTC)).timestamp()
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time(), tzinfo=dt.UTC).timestamp()
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    raise ValueError(f"Unsupported AWS Config incremental value: {value!r}")


def incremental_start(
    endpoint: AwsConfigEndpoint, should_use_incremental_field: bool, last_value: Any, now: dt.datetime
) -> float | None:
    if endpoint.incremental_field is None:
        return None
    if should_use_incremental_field and last_value is not None:
        return epoch_seconds(last_value)
    if endpoint.initial_window is not None:
        return (now - endpoint.initial_window).timestamp()
    return None


def snake_case(key: str) -> str:
    return _CAMEL_BOUNDARY.sub("_", key).lower()


def normalize_row(item: dict[str, Any], region: str, flatten: tuple[str, ...] = ()) -> dict[str, Any]:
    for key in flatten:
        nested = item.get(key)
        if isinstance(nested, dict):
            item = {**nested, **{name: value for name, value in item.items() if name != key}}
    row = {snake_case(key): value for key, value in item.items()}
    row["region"] = region
    for key in _TIMESTAMP_COLUMNS & row.keys():
        value = row[key]
        if isinstance(value, int | float) and not isinstance(value, bool):
            row[key] = dt.datetime.fromtimestamp(value, tz=dt.UTC)
        elif isinstance(value, str) and value:
            row[key] = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return row


def parse_page(
    endpoint: AwsConfigEndpoint, body: dict[str, Any], region: str, previous_token: str | None
) -> tuple[list[dict[str, Any]], str | None]:
    rows = []
    for item in body.get(endpoint.result_key) or []:
        if endpoint.expression is not None:
            item = json.loads(item)
        if not isinstance(item, dict):
            raise ValueError("AWS Config returned an invalid resource. Try the sync again.")
        rows.append(normalize_row(item, region, endpoint.flatten))
    token = body.get(endpoint.token_key) or None
    if token is not None and (not isinstance(token, str) or token == previous_token):
        raise ValueError("AWS Config returned an invalid page token. Try the sync again.")
    return rows, token


def request_page(
    client: AwsConfigClient,
    operation: str,
    payload: dict[str, Any],
    manager: "ResumableSourceManager[AwsConfigResumeConfig]",
    resumed: bool,
    empty_error_codes: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    try:
        return client.request(operation, payload)
    except AwsConfigError as error:
        if error.code in empty_error_codes:
            return {}
        if resumed and error.code == "InvalidNextTokenException":
            # A fresh retry must restart the full-refresh destination as well as extraction.
            manager.clear_state()
        raise


def get_page_rows(
    client: AwsConfigClient,
    endpoint: AwsConfigEndpoint,
    manager: "ResumableSourceManager[AwsConfigResumeConfig]",
    resume: AwsConfigResumeConfig | None,
    since: float | None,
) -> Generator[list[dict[str, Any]]]:
    next_token = resume.next_token if resume else None
    restarting = next_token is not None
    while True:
        payload = request_payload(endpoint, since=since)
        if next_token:
            payload[endpoint.token_key] = next_token
        body = request_page(client, endpoint.operation, payload, manager, restarting)
        restarting = False
        rows, next_token = parse_page(endpoint, body, client.region, next_token)
        manager.save_state(AwsConfigResumeConfig(next_token=next_token, complete=next_token is None, since=since))
        if rows:
            yield rows
        manager.safe_point()
        if next_token is None:
            break


def parent_values(parent: AwsConfigEndpoint, item: Any, params: tuple[str, ...]) -> tuple[str, ...]:
    if parent.expression is not None and isinstance(item, str):
        try:
            item = json.loads(item)
        except ValueError:
            item = None
    values: list[str] = []
    for param in params:
        value = item.get(param) if isinstance(item, dict) else None
        if not isinstance(value, str) or not value:
            raise ValueError("AWS Config returned an invalid parent resource. Try the sync again.")
        values.append(value)
    return tuple(values)


def parent_key(values: tuple[str, ...]) -> str:
    # Single-value keys stay plain strings so checkpoints saved before composite keys still resume.
    return values[0] if len(values) == 1 else json.dumps(values)


def get_fan_out_rows(
    client: AwsConfigClient,
    endpoint: AwsConfigEndpoint,
    manager: "ResumableSourceManager[AwsConfigResumeConfig]",
    resume: AwsConfigResumeConfig | None,
    since: float | None,
) -> Generator[list[dict[str, Any]]]:
    parent, params = endpoint.parent, endpoint.parent_params
    if parent is None or not params:
        raise ValueError(f"AWS Config table {endpoint.operation} has no parent.")
    columns = [snake_case(param) for param in params]
    parent_token = resume.parent_next_token if resume else None
    resume_key = resume.parent_key if resume else None
    child_token = resume.next_token if resume else None
    restarting_parent = parent_token is not None
    restarting_child = child_token is not None
    while True:
        payload = request_payload(parent)
        if parent_token:
            payload[parent.token_key] = parent_token
        body = request_page(client, parent.operation, payload, manager, restarting_parent)
        restarting_parent = False
        parents = [parent_values(parent, item, params) for item in body.get(parent.result_key) or []]
        names = [parent_key(values) for values in parents]
        next_parent_token = body.get(parent.token_key) or None
        if next_parent_token is not None and (
            not isinstance(next_parent_token, str) or next_parent_token == parent_token
        ):
            raise ValueError("AWS Config returned an invalid page token. Try the sync again.")
        if resume_key is not None and resume_key not in names:
            # Replaying the page would append committed rows twice, so the retry must restart the destination.
            manager.clear_state()
            raise ValueError("An AWS Config parent resource changed during the sync. Try the sync again.")
        start = names.index(resume_key) if resume_key is not None else 0
        resume_key = None
        if not names:
            manager.save_state(
                AwsConfigResumeConfig(parent_next_token=next_parent_token, since=since)
                if next_parent_token is not None
                else AwsConfigResumeConfig(complete=True)
            )
            manager.safe_point()
        for index in range(start, len(names)):
            name = names[index]
            values = parents[index]
            if index + 1 < len(names):
                done = AwsConfigResumeConfig(parent_next_token=parent_token, parent_key=names[index + 1], since=since)
            elif next_parent_token is not None:
                done = AwsConfigResumeConfig(parent_next_token=next_parent_token, since=since)
            else:
                done = AwsConfigResumeConfig(complete=True)
            while True:
                child_payload = {**request_payload(endpoint, since=since), **dict(zip(params, values))}
                if child_token:
                    child_payload[endpoint.token_key] = child_token
                child_body = request_page(
                    client, endpoint.operation, child_payload, manager, restarting_child, endpoint.empty_error_codes
                )
                restarting_child = False
                rows, child_token = parse_page(endpoint, child_body, client.region, child_token)
                for row in rows:
                    row.update(zip(columns, values))
                manager.save_state(
                    AwsConfigResumeConfig(
                        parent_next_token=parent_token, parent_key=name, next_token=child_token, since=since
                    )
                    if child_token is not None
                    else done
                )
                if rows:
                    yield rows
                manager.safe_point()
                if child_token is None:
                    break
        if next_parent_token is None:
            break
        parent_token = next_parent_token


def get_rows(
    config: "AwsConfigSourceConfig",
    endpoint: AwsConfigEndpoint,
    api_version: str,
    manager: "ResumableSourceManager[AwsConfigResumeConfig]",
    since: float | None = None,
) -> Generator[list[dict[str, Any]]]:
    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None and resume.complete:
        manager.clear_state()
        return
    if resume is not None and resume.since is not None:
        since = resume.since
    client = AwsConfigClient(config, api_version)
    try:
        if endpoint.parent is None:
            yield from get_page_rows(client, endpoint, manager, resume, since)
        else:
            yield from get_fan_out_rows(client, endpoint, manager, resume, since)
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
    probe = endpoint.parent or endpoint
    operation = probe.operation
    try:
        body = client.request(operation, request_payload(probe, probe=True))
        if endpoint.parent is not None and endpoint.parent_params:
            parents = body.get(endpoint.parent.result_key) or []
            if parents:
                values = parent_values(endpoint.parent, parents[0], endpoint.parent_params)
                operation = endpoint.operation
                try:
                    client.request(
                        operation,
                        {**request_payload(endpoint, probe=True), **dict(zip(endpoint.parent_params, values))},
                    )
                except AwsConfigError as error:
                    if error.code not in endpoint.empty_error_codes:
                        raise
    except AwsConfigError as error:
        if error.code in {"AccessDenied", "AccessDeniedException"}:
            if schema_name is None:
                return True, None
            return False, f"Grant config:{operation} to this IAM user or role to sync this table."
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
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    endpoint_config = AWS_CONFIG_ENDPOINTS.get(endpoint)
    if endpoint_config is None:
        raise ValueError(f"Unknown AWS Config table: {endpoint}")
    since = incremental_start(
        endpoint_config, should_use_incremental_field, db_incremental_field_last_value, dt.datetime.now(dt.UTC)
    )
    partition_key = endpoint_config.partition_key
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(config, endpoint_config, api_version, manager, since),
        primary_keys=list(endpoint_config.primary_key),
        partition_count=1 if partition_key else None,
        partition_size=1 if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
        sort_mode=None,
    )
