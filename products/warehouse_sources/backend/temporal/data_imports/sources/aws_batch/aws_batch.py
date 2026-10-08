import re
import json
import datetime as dt
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.session import Session
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_batch.settings import (
    AWS_BATCH_ENDPOINTS,
    BATCH_API_VERSION,
    NON_RETRYABLE_ERRORS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsbatch import (
    AwsBatchSourceConfig,
)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_REGION = re.compile(r"(?:af|ap|ca|cn|eu|il|me|mx|sa|us)-(?:gov-)?[a-z]+-\d+")

TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"POST"}),
    raise_on_status=False,
)


@frozen
class AwsBatchResumeConfig:
    next_token: str | None = None
    queue_arns: list[str] | None = None
    queue_index: int = 0
    complete: bool = False


class AwsBatchError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"AWS Batch request failed: {code} - {message}")
        self.code = code
        self.message = message

    @property
    def access_denied(self) -> bool:
        return "AccessDenied" in self.code or (
            self.code == "ClientException" and "not authorized to perform" in self.message
        )


class AwsBatchThrottleError(AwsBatchError):
    pass


def error_for_response(response: requests.Response) -> AwsBatchError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    code = str(
        response.headers.get("x-amzn-ErrorType")
        or body.get("__type")
        or body.get("code")
        or f"HTTP {response.status_code}"
    )
    code = code.split(":")[0].split("#")[-1]
    message = str(body.get("message") or body.get("Message") or response.text)[:500]
    # The transport retries HTTP 429 and 5xx. Only body-level throttles need another retry policy.
    if response.status_code == 400 and code in {"ThrottlingException", "TooManyRequestsException", "Throttling"}:
        return AwsBatchThrottleError(code, message)
    return AwsBatchError(code, message)


class AwsBatchClient:
    def __init__(self, config: AwsBatchSourceConfig, api_version: str = BATCH_API_VERSION) -> None:
        if api_version != BATCH_API_VERSION:
            raise ValueError(f"Unsupported AWS Batch API version: {api_version}")
        if not _REGION.fullmatch(config.region):
            raise ValueError("Enter an AWS region, such as us-east-1.")
        suffix = "amazonaws.com.cn" if config.region.startswith("cn-") else "amazonaws.com"
        self.url = f"https://batch.{config.region}.{suffix}"
        # REST-JSON has no version header. The pinned service model selects its request paths.
        self.model = Session().get_service_model("batch", api_version=api_version)
        self.signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            "batch",
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

    @retry(
        retry=retry_if_exception_type(AwsBatchThrottleError),
        stop=stop_after_attempt(4),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.url + self.model.operation_model(operation).http["requestUri"]
        body = json.dumps(payload).encode("utf-8")
        request = AWSRequest(method="POST", url=url, data=body, headers={"Content-Type": "application/json"})
        self.signer.add_auth(request)
        response = self.session.post(url, data=body, headers=dict(request.headers), timeout=60)
        if response.status_code >= 400:
            raise error_for_response(response)
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise ValueError("AWS Batch returned an invalid response.")
        return parsed

    def close(self) -> None:
        self.session.close()


def normalize_row(item: dict[str, Any], region: str) -> dict[str, Any]:
    row = {_CAMEL_BOUNDARY.sub("_", name).lower(): value for name, value in item.items()}
    row["region"] = region
    for column in ("created_at", "started_at", "stopped_at", "scheduled_at"):
        if column in row and isinstance(row[column], int | float) and not isinstance(row[column], bool):
            row[column] = dt.datetime.fromtimestamp(row[column] / 1000, tz=dt.UTC) if row[column] else None
    return row


def next_page_token(body: dict[str, Any], previous_token: str | None) -> str | None:
    token = body.get("nextToken") or None
    if token is not None and (not isinstance(token, str) or token == previous_token):
        raise ValueError("AWS Batch returned an invalid or repeated page token.")
    return token


def discover_queues(client: AwsBatchClient, manager: ResumableSourceManager[AwsBatchResumeConfig]) -> list[str]:
    queues: list[str] = []
    token = None
    while True:
        payload: dict[str, Any] = {"maxResults": PAGE_SIZE}
        if token:
            payload["nextToken"] = token
        body = client.request("DescribeJobQueues", payload)
        queues.extend(queue["jobQueueArn"] for queue in body.get("jobQueues", []))
        token = next_page_token(body, token)
        manager.safe_point()
        if token is None:
            return list(dict.fromkeys(queues))


def get_rows(
    config: AwsBatchSourceConfig,
    endpoint: str,
    manager: ResumableSourceManager[AwsBatchResumeConfig],
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = AWS_BATCH_ENDPOINTS[endpoint]
    state = manager.load_state() if manager.can_resume() else None
    state = state or AwsBatchResumeConfig()
    if state.complete:
        return
    client = AwsBatchClient(config, api_version)
    try:
        if endpoint == "jobs" and state.queue_arns is None:
            state = replace(state, queue_arns=discover_queues(client, manager))
        while not state.complete:
            payload: dict[str, Any] = {"maxResults": PAGE_SIZE}
            if endpoint == "jobs":
                queues = state.queue_arns or []
                if state.queue_index >= len(queues):
                    manager.save_state(replace(state, complete=True))
                    manager.safe_point()
                    return
                payload["jobQueue"] = queues[state.queue_index]
                # A name wildcard includes every status without seven separate status walks.
                payload["filters"] = [{"name": "JOB_NAME", "values": ["*"]}]
            if state.next_token:
                payload["nextToken"] = state.next_token
            body = client.request(endpoint_config.operation, payload)
            items = body.get(endpoint_config.result_key, [])
            token = next_page_token(body, state.next_token)
            if endpoint == "jobs":
                job_ids = [item["jobId"] for item in items]
                items = []
                for offset in range(0, len(job_ids), PAGE_SIZE):
                    items.extend(
                        client.request("DescribeJobs", {"jobs": job_ids[offset : offset + PAGE_SIZE]}).get("jobs", [])
                    )
                queue_index = state.queue_index + (token is None)
                state = replace(state, next_token=token, queue_index=queue_index, complete=queue_index >= len(queues))
            else:
                state = replace(state, next_token=token, complete=token is None)
            rows = [normalize_row(item, config.region) for item in items]
            manager.save_state(state)
            if rows:
                yield rows
            manager.safe_point()
    finally:
        client.close()


def credential_error_message(error: AwsBatchError) -> str:
    for pattern, message in NON_RETRYABLE_ERRORS.items():
        if pattern in str(error):
            return message
    return "Could not read AWS Batch data. Check the region and IAM permissions, then try again."


def validate_credentials(
    config: AwsBatchSourceConfig,
    schema_name: str | None = None,
    api_version: str = BATCH_API_VERSION,
) -> tuple[bool, str | None]:
    if not config.aws_access_key_id or not config.aws_secret_access_key:
        return False, "Enter both an AWS access key ID and a secret access key."
    if schema_name is not None and schema_name not in AWS_BATCH_ENDPOINTS:
        return False, f"Unknown AWS Batch table: {schema_name}"
    try:
        client = AwsBatchClient(config, api_version)
    except ValueError as error:
        return False, str(error)
    try:
        operation = AWS_BATCH_ENDPOINTS[schema_name].operation if schema_name else "DescribeJobQueues"
        if schema_name == "jobs":
            queues = client.request("DescribeJobQueues", {"maxResults": 1}).get("jobQueues", [])
            if queues:
                jobs = client.request(
                    "ListJobs",
                    {
                        "jobQueue": queues[0]["jobQueueArn"],
                        "maxResults": 1,
                        "filters": [{"name": "JOB_NAME", "values": ["*"]}],
                    },
                ).get("jobSummaryList", [])
                if jobs:
                    client.request("DescribeJobs", {"jobs": [jobs[0]["jobId"]]})
        else:
            client.request(operation, {"maxResults": 1})
    except AwsBatchError as error:
        if schema_name is None and error.access_denied:
            return True, None
        return False, credential_error_message(error)
    except requests.RequestException:
        return False, "Could not reach AWS Batch. Check the region and try again."
    finally:
        client.close()
    return True, None


def aws_batch_source(
    config: AwsBatchSourceConfig,
    endpoint: str,
    manager: ResumableSourceManager[AwsBatchResumeConfig],
    api_version: str = BATCH_API_VERSION,
) -> SourceResponse:
    endpoint_config = AWS_BATCH_ENDPOINTS.get(endpoint)
    if endpoint_config is None:
        raise ValueError(f"Unknown AWS Batch table: {endpoint}")
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(config, endpoint, manager, api_version),
        primary_keys=[endpoint_config.primary_key],
        sort_mode=None,
        on_complete=manager.clear_state,
    )
