import re
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.aws_end_user_messaging._config import AwsEndUserMessagingSourceConfig
from products.warehouse_sources.sources.aws_end_user_messaging.settings import (
    CONTENT_TYPE,
    ENDPOINTS,
    ERROR_MESSAGES,
    ERROR_PREFIX,
    PAGE_SIZE,
    SIGNING_NAME,
    TARGET_PREFIX,
    THROTTLING_CODES,
    Endpoint,
    FanOut,
)
from products.warehouse_sources.sources.sdk import (
    BoundedRetry,
    ResumableSourceManager,
    SourceResponse,
    camel_to_snake,
    frozen,
    make_tracked_session,
    probe_status_message,
    retry_with_deadline,
)

_REGION = re.compile(r"[a-z]{2}(?:-[a-z]+)+-\d+")
TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"POST"}),
    raise_on_status=False,
)


class AwsEndUserMessagingError(Exception):
    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(f"{ERROR_PREFIX}: {code} - {message}")


class AwsEndUserMessagingThrottleError(AwsEndUserMessagingError):
    pass


@frozen
class AwsEndUserMessagingResumeConfig:
    # The page token of the table, or of the current parent table for a fan-out table.
    next_token: str | None = None
    complete: bool = False
    # Fan-out tables only. The parent table in `FanOut.parents` that the sync reads now.
    parent_index: int = 0
    # Parent identities from the current parent page that are not done. The first one is in progress.
    pending: tuple[str, ...] = ()
    # The page token of the child request for the first pending parent.
    child_token: str | None = None


def error_for_response(response: requests.Response) -> AwsEndUserMessagingError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw_code = response.headers.get("x-amzn-ErrorType") or body.get("__type") or body.get("code")
    code = str(raw_code or f"HTTP {response.status_code}").split(":", 1)[0].rsplit("#", 1)[-1]
    message = str(body.get("message") or body.get("Message") or response.reason or "")[:500]
    # The transport retries HTTP statuses, but AWS sends ThrottlingException with HTTP 400.
    if code in THROTTLING_CODES:
        return AwsEndUserMessagingThrottleError(code, message, response.status_code)
    return AwsEndUserMessagingError(code, message, response.status_code)


class AwsEndUserMessagingClient:
    def __init__(self, config: AwsEndUserMessagingSourceConfig) -> None:
        if not config.aws_access_key_id or not config.aws_secret_access_key:
            raise ValueError("Enter both an AWS access key ID and a secret access key.")
        region = (config.aws_region or "").strip()
        if not _REGION.fullmatch(region):
            raise ValueError("Enter an AWS region, such as us-east-1.")
        suffix = "amazonaws.com.cn" if region.startswith("cn-") else "amazonaws.com"
        self.url = f"https://{SIGNING_NAME}.{region}.{suffix}/"
        self.signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            SIGNING_NAME,
            region,
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

    @retry_with_deadline(
        retry=retry_if_exception_type(AwsEndUserMessagingThrottleError),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=20),
        reraise=True,
    )
    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = AWSRequest(
            method="POST",
            url=self.url,
            data=body,
            headers={"Content-Type": CONTENT_TYPE, "X-Amz-Target": f"{TARGET_PREFIX}.{operation}"},
        )
        self.signer.add_auth(request)
        response = self.session.post(
            self.url, data=body, headers=dict(request.headers), timeout=60, allow_redirects=False
        )
        if not 200 <= response.status_code < 300:
            raise error_for_response(response)
        try:
            result = response.json()
        except ValueError:
            result = None
        if not isinstance(result, dict):
            raise AwsEndUserMessagingError("InvalidResponse", "AWS returned a response that is not a JSON object.")
        return result

    def page(self, operation: str, token: str | None, **params: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {"MaxResults": PAGE_SIZE, **params}
        if token:
            payload["NextToken"] = token
        return self.request(operation, payload)


def normalize_row(item: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in item.items():
        column = camel_to_snake(key)
        # The JSON protocol sends timestamps as epoch seconds.
        if column.endswith("timestamp") and isinstance(value, (int, float)) and not isinstance(value, bool):
            value = datetime.fromtimestamp(value, tz=UTC)
        row[column] = value
    return row


def _next_token(result: dict[str, Any], seen: set[str]) -> str | None:
    token = result.get("NextToken") or None
    if token is not None:
        if token in seen:
            raise AwsEndUserMessagingError("RepeatedNextToken", "AWS repeated a pagination token. Restart the sync.")
        seen.add(token)
    return token


def _settle(state: AwsEndUserMessagingResumeConfig, fan_out: FanOut) -> AwsEndUserMessagingResumeConfig:
    # A parent table is done when its last page is read and no parent from it is pending.
    if state.pending or state.next_token is not None:
        return state
    parent_index = state.parent_index + 1
    return replace(state, parent_index=parent_index, child_token=None, complete=parent_index >= len(fan_out.parents))


def _fan_out_rows(
    client: AwsEndUserMessagingClient,
    endpoint: Endpoint,
    fan_out: FanOut,
    manager: ResumableSourceManager[AwsEndUserMessagingResumeConfig],
    state: AwsEndUserMessagingResumeConfig,
) -> Iterator[list[dict[str, Any]]]:
    seen: set[str] = {token for token in (state.next_token, state.child_token) if token}
    while not state.complete:
        rows: list[dict[str, Any]] = []
        if state.pending:
            identity = state.pending[0]
            try:
                result = client.page(endpoint.operation, state.child_token, **{fan_out.request_field: identity})
            except AwsEndUserMessagingError as error:
                # The parent can be deleted between the parent listing and this request.
                if error.code != "ResourceNotFoundException":
                    raise
                result = {}
            parent_arn = result.get(fan_out.response_arn_field) or identity
            parent_columns = {
                fan_out.arn_column: parent_arn,
                fan_out.name_column: result.get(fan_out.response_name_field),
                **{column: result.get(field) for field, column in fan_out.extra_columns},
            }
            rows = [{**parent_columns, **normalize_row(item)} for item in result.get(endpoint.result_key) or []]
            child_token = _next_token(result, seen)
            if child_token is not None:
                state = replace(state, child_token=child_token)
            else:
                state = _settle(replace(state, pending=state.pending[1:], child_token=None), fan_out)
        else:
            parent_name, id_field = fan_out.parents[state.parent_index]
            parent = ENDPOINTS[parent_name]
            page = client.page(parent.operation, state.next_token)
            pending = tuple(str(item[id_field]) for item in page.get(parent.result_key) or [] if item.get(id_field))
            state = _settle(replace(state, next_token=_next_token(page, seen), pending=pending), fan_out)
        manager.save_state(state)
        if rows:
            yield rows
        manager.safe_point()


def get_rows(
    config: AwsEndUserMessagingSourceConfig,
    endpoint_name: str,
    manager: ResumableSourceManager[AwsEndUserMessagingResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    endpoint = ENDPOINTS[endpoint_name]
    state = (manager.load_state() if manager.can_resume() else None) or AwsEndUserMessagingResumeConfig()
    state = replace(state, pending=tuple(state.pending))
    if state.complete:
        return
    client = AwsEndUserMessagingClient(config)
    try:
        if endpoint.fan_out is not None:
            yield from _fan_out_rows(client, endpoint, endpoint.fan_out, manager, state)
            return
        token = state.next_token
        seen: set[str] = {token} if token else set()
        while True:
            result = client.page(endpoint.operation, token)
            rows = [normalize_row(item) for item in result.get(endpoint.result_key) or []]
            token = _next_token(result, seen)
            manager.save_state(AwsEndUserMessagingResumeConfig(next_token=token, complete=token is None))
            if rows:
                yield rows
            manager.safe_point()
            if token is None:
                return
    finally:
        client.close()


def _probe(client: AwsEndUserMessagingClient, schema_name: str | None) -> None:
    if schema_name is None:
        client.request("DescribeAccountAttributes", {"MaxResults": 1})
        return
    endpoint = ENDPOINTS[schema_name]
    if endpoint.fan_out is None:
        client.request(endpoint.operation, {"MaxResults": 1})
        return
    # A child request needs a parent identity, so take the first one that a parent table lists.
    for parent_name, id_field in endpoint.fan_out.parents:
        parent = ENDPOINTS[parent_name]
        items = client.request(parent.operation, {"MaxResults": 1}).get(parent.result_key) or []
        if items and items[0].get(id_field):
            payload = {"MaxResults": 1, endpoint.fan_out.request_field: str(items[0][id_field])}
            client.request(endpoint.operation, payload)
            return


def validate_credentials(
    config: AwsEndUserMessagingSourceConfig, schema_name: str | None = None
) -> tuple[bool, str | None]:
    if schema_name is not None and schema_name not in ENDPOINTS:
        return False, f"Unknown AWS End User Messaging table: {schema_name}"
    try:
        client = AwsEndUserMessagingClient(config)
    except ValueError as error:
        return False, str(error)
    try:
        _probe(client, schema_name)
    except AwsEndUserMessagingError as error:
        if error.code == "ResourceNotFoundException" and schema_name is not None:
            return True, None
        if error.code in {"AccessDenied", "AccessDeniedException"}:
            # AWS checks the signature before the permissions, so the credentials are genuine.
            if schema_name is None:
                return True, None
            return False, (
                f"AWS denied access. Grant sms-voice:{ENDPOINTS[schema_name].operation} "
                "to the IAM user or role to sync this table."
            )
        if error.code in ERROR_MESSAGES:
            return False, ERROR_MESSAGES[error.code]
        status_message = probe_status_message("AWS End User Messaging", error.status_code)
        if status_message:
            return False, status_message
        return False, f"AWS End User Messaging returned an error: {error.code}. Try again."
    except requests.RequestException:
        return False, (
            "Could not reach AWS End User Messaging in this region. Check that the region is correct "
            "and that AWS End User Messaging SMS is available in it."
        )
    finally:
        client.close()
    return True, None


def aws_end_user_messaging_source(
    config: AwsEndUserMessagingSourceConfig,
    endpoint: str,
    manager: ResumableSourceManager[AwsEndUserMessagingResumeConfig],
) -> SourceResponse:
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown AWS End User Messaging table: {endpoint}")
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(config, endpoint, manager),
        primary_keys=list(ENDPOINTS[endpoint].primary_keys),
        sort_mode=None,
        on_complete=manager.clear_state,
    )
