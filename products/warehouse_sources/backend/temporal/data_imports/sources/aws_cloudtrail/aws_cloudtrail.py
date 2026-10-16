import re
import json
import time
import datetime as dt
from collections.abc import Iterator
from typing import Any

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cloudtrail.settings import (
    ACCESS_DENIED_CODES,
    AWS_CLOUDTRAIL_ENDPOINTS,
    CREDENTIAL_ERRORS,
    LOOKBACK_SECONDS,
    TARGET_PREFIXES,
    THROTTLE_CODES,
    CloudTrailEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["POST"]),
    raise_on_status=False,
)


@frozen
class AwsCloudTrailResumeConfig:
    next_token: str | None = None
    start_time: float | None = None
    end_time: float | None = None
    finished: bool = False


class AwsCloudTrailError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(f"AWS CloudTrail request failed: {code}")
        self.code = code


class AwsCloudTrailThrottled(AwsCloudTrailError):
    pass


def error_for_response(response: requests.Response) -> AwsCloudTrailError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw_code = response.headers.get("x-amzn-ErrorType") or body.get("__type") or body.get("code")
    code = str(raw_code or f"HTTP {response.status_code}").split(":")[0].rsplit("#", 1)[-1]
    # The transport retries HTTP statuses. Only body-level throttles need a separate retry.
    if response.status_code == 400 and code in THROTTLE_CODES:
        return AwsCloudTrailThrottled(code)
    return AwsCloudTrailError(code)


class AwsCloudTrailClient:
    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        session_token: str | None,
        region: str,
        api_version: str,
    ) -> None:
        if not access_key_id or not secret_access_key:
            raise ValueError("Enter both an AWS access key ID and a secret access key.")
        if not re.fullmatch(r"(?:af|ap|ca|eu|il|me|mx|sa|us|cn)-(?:gov-)?[a-z]+-\d+", region):
            raise ValueError("Enter a valid AWS region, such as us-east-1.")
        if api_version not in TARGET_PREFIXES:
            raise ValueError(f"Unsupported AWS CloudTrail API version: {api_version}")
        self.region = region
        self.target_prefix = TARGET_PREFIXES[api_version]
        suffix = "amazonaws.com.cn" if region.startswith("cn-") else "amazonaws.com"
        self.url = f"https://cloudtrail.{region}.{suffix}/"
        self.signer = SigV4Auth(
            Credentials(access_key_id, secret_access_key, session_token or None), "cloudtrail", region
        )
        self.session = make_tracked_session(
            retry=TRANSPORT_RETRY,
            redact_values=tuple(value for value in (access_key_id, secret_access_key, session_token) if value),
        )
        self._last_lookup: float | None = None

    @retry(
        retry=retry_if_exception_type(AwsCloudTrailThrottled),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation == "LookupEvents":
            if self._last_lookup is not None:
                time.sleep(max(0, 0.5 - (time.monotonic() - self._last_lookup)))
            self._last_lookup = time.monotonic()
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
        self.signer.add_auth(request)
        response = self.session.post(
            self.url, data=body, headers=dict(request.headers), timeout=60, allow_redirects=False
        )
        if not 200 <= response.status_code < 300:
            raise error_for_response(response)
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise ValueError("AWS CloudTrail returned an invalid response.")
        return parsed

    def close(self) -> None:
        self.session.close()


def normalize_row(item: dict[str, Any], endpoint: CloudTrailEndpoint, region: str) -> dict[str, Any]:
    row = {_CAMEL_BOUNDARY.sub("_", key).lower(): value for key, value in item.items()}
    row["region"] = region
    for column in endpoint.timestamps:
        value = row.get(column)
        if isinstance(value, int | float) and not isinstance(value, bool):
            row[column] = dt.datetime.fromtimestamp(value, dt.UTC)
    return row


def request_payload(endpoint: CloudTrailEndpoint, page_size: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if endpoint.page_size is not None:
        payload["MaxResults"] = page_size or endpoint.page_size
    if endpoint.event_category is not None:
        payload["EventCategory"] = endpoint.event_category
    if endpoint.operation == "DescribeTrails":
        payload["includeShadowTrails"] = True
    return payload


def get_rows(
    client: AwsCloudTrailClient,
    endpoint: CloudTrailEndpoint,
    manager: ResumableSourceManager[AwsCloudTrailResumeConfig],
    last_value: dt.datetime | str | int | float | None,
) -> Iterator[list[dict[str, Any]]]:
    try:
        state = manager.load_state() or AwsCloudTrailResumeConfig()
        if state.finished:
            return
        start_time, end_time = state.start_time, state.end_time
        if endpoint.is_events and end_time is None:
            end_time = dt.datetime.now(dt.UTC).timestamp()
            if last_value is not None:
                if isinstance(last_value, str):
                    last_value = dt.datetime.fromisoformat(last_value.replace("Z", "+00:00"))
                if isinstance(last_value, dt.datetime):
                    if last_value.tzinfo is None:
                        last_value = last_value.replace(tzinfo=dt.UTC)
                    last_value = last_value.timestamp()
                start_time = max(float(last_value), end_time - LOOKBACK_SECONDS)
        payload = request_payload(endpoint)
        if endpoint.is_events:
            payload["EndTime"] = end_time
            if start_time is not None:
                payload["StartTime"] = start_time
        next_token = state.next_token
        restarted = False
        while True:
            params = dict(payload)
            if next_token:
                params["NextToken"] = next_token
            try:
                body = client.request(endpoint.operation, params)
            except AwsCloudTrailError as error:
                if error.code == "InvalidNextTokenException" and state.next_token and not restarted:
                    next_token = None
                    restarted = True
                    continue
                raise
            next_token = body.get("NextToken") if endpoint.page_size is not None else None
            if next_token and next_token == params.get("NextToken"):
                raise ValueError("AWS CloudTrail returned a repeated page token.")
            rows = [normalize_row(item, endpoint, client.region) for item in body.get(endpoint.result_key, [])]
            manager.save_state(
                AwsCloudTrailResumeConfig(
                    next_token=next_token, start_time=start_time, end_time=end_time, finished=not next_token
                )
            )
            if rows:
                yield rows
            manager.safe_point()
            if not next_token:
                break
    finally:
        client.close()


def validate_credentials(
    access_key_id: str,
    secret_access_key: str,
    session_token: str | None,
    region: str,
    api_version: str,
    schema_name: str | None = None,
) -> tuple[bool, str | None]:
    endpoint = AWS_CLOUDTRAIL_ENDPOINTS.get(schema_name or "trails")
    if endpoint is None:
        return False, f"Unknown AWS CloudTrail table: {schema_name}"
    try:
        client = AwsCloudTrailClient(access_key_id, secret_access_key, session_token, region, api_version)
    except ValueError as error:
        return False, str(error)
    try:
        client.request(endpoint.operation, request_payload(endpoint, page_size=1))
    except AwsCloudTrailError as error:
        if error.code in ACCESS_DENIED_CODES:
            if schema_name is None:
                return True, None
            return False, f"Grant the cloudtrail:{endpoint.operation} IAM permission to read this table."
        return False, CREDENTIAL_ERRORS.get(error.code, "Could not read from AWS CloudTrail. Try again.")
    except (requests.RequestException, ValueError):
        return False, "Could not reach the AWS CloudTrail API. Check the selected region and try again."
    finally:
        client.close()
    return True, None


def aws_cloudtrail_source(
    access_key_id: str,
    secret_access_key: str,
    session_token: str | None,
    region: str,
    api_version: str,
    endpoint_name: str,
    manager: ResumableSourceManager[AwsCloudTrailResumeConfig],
    last_value: dt.datetime | str | int | float | None,
) -> SourceResponse:
    endpoint = AWS_CLOUDTRAIL_ENDPOINTS.get(endpoint_name)
    if endpoint is None:
        raise ValueError(f"Unknown AWS CloudTrail table: {endpoint_name}")
    return SourceResponse(
        name=endpoint_name,
        items=lambda: get_rows(
            AwsCloudTrailClient(access_key_id, secret_access_key, session_token, region, api_version),
            endpoint,
            manager,
            last_value,
        ),
        primary_keys=list(endpoint.primary_key),
        sort_mode="desc" if endpoint.is_events else None,
        partition_keys=["event_time"] if endpoint.is_events else None,
        partition_mode="datetime" if endpoint.is_events else None,
        partition_format="month" if endpoint.is_events else None,
        on_complete=manager.clear_state,
    )
