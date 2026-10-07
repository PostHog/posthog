import re
import json
from collections.abc import Iterator
from dataclasses import field, replace
from datetime import UTC, datetime
from typing import Any

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_step_functions.settings import (
    CONTENT_TYPE,
    ENDPOINTS,
    ERROR_MESSAGES,
    PAGE_SIZE,
    TARGET_PREFIXES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsstepfunctions import (
    AwsStepFunctionsSourceConfig,
)


class AwsStepFunctionsError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"AWS Step Functions request failed: {code} - {message}")


class AwsStepFunctionsThrottle(AwsStepFunctionsError):
    pass


@frozen
class AwsStepFunctionsResumeConfig:
    machine_token: str | None = None
    machine_arns: list[str] = field(default_factory=list)
    machines_done: bool = False
    execution_token: str | None = None
    execution_arns: list[str] = field(default_factory=list)
    executions_done: bool = False
    history_token: str | None = None


class AwsStepFunctionsClient:
    def __init__(self, config: AwsStepFunctionsSourceConfig, api_version: str) -> None:
        if api_version not in TARGET_PREFIXES:
            raise ValueError(f"Unsupported AWS Step Functions API version: {api_version}")
        if not config.aws_access_key_id or not config.aws_secret_access_key:
            raise ValueError("Enter both an AWS access key ID and a secret access key.")
        if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", config.region):
            raise ValueError("Enter an AWS region, such as us-east-1.")
        suffix = "amazonaws.com.cn" if config.region.startswith("cn-") else "amazonaws.com"
        self.url = f"https://states.{config.region}.{suffix}/"
        self.target_prefix = TARGET_PREFIXES[api_version]
        self.signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            "states",
            config.region,
        )
        self.session = make_tracked_session(
            retry=BoundedRetry(
                total=3,
                backoff_factor=1,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset(["POST"]),
                raise_on_status=False,
            ),
            redact_values=tuple(value for value in (config.aws_secret_access_key, config.aws_session_token) if value),
        )

    # AWS also reports throttling as HTTP 400, outside the transport's status retries.
    @retry(
        retry=retry_if_exception_type(AwsStepFunctionsThrottle),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode()
        request = AWSRequest(
            method="POST",
            url=self.url,
            data=body,
            headers={"Content-Type": CONTENT_TYPE, "X-Amz-Target": f"{self.target_prefix}.{operation}"},
        )
        self.signer.add_auth(request)
        response = self.session.post(
            self.url, data=body, headers=dict(request.headers), timeout=60, allow_redirects=False
        )
        if response.status_code >= 400:
            try:
                error = response.json()
            except ValueError:
                error = {}
            if not isinstance(error, dict):
                error = {}
            code = (
                str(
                    response.headers.get("x-amzn-ErrorType")
                    or error.get("__type")
                    or error.get("code")
                    or f"HTTP {response.status_code}"
                )
                .split(":")[0]
                .rsplit("#", 1)[-1]
            )
            message = str(error.get("message") or error.get("Message") or response.reason)[:500]
            error_class = (
                AwsStepFunctionsThrottle
                if response.status_code == 400
                and code in {"ThrottlingException", "Throttling", "TooManyRequestsException", "KmsThrottlingException"}
                else AwsStepFunctionsError
            )
            raise error_class(code, message)
        if response.status_code != 200:
            raise AwsStepFunctionsError(f"HTTP {response.status_code}", "Unexpected AWS response status.")
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("AWS Step Functions returned an invalid response.")
        return result

    def page(self, endpoint: str, token: str | None = None, **params: Any) -> dict[str, Any]:
        payload = {"maxResults": PAGE_SIZE, **params}
        if token:
            payload["nextToken"] = token
        return self.request(ENDPOINTS[endpoint].operation, payload)

    def close(self) -> None:
        self.session.close()


def normalize_row(item: dict[str, Any]) -> dict[str, Any]:
    row = {re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key).lower(): value for key, value in item.items()}
    for key in ("creation_date", "start_date", "stop_date", "redrive_date", "timestamp"):
        value = row.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            row[key] = datetime.fromtimestamp(value, tz=UTC)
    return row


def get_rows(
    client: AwsStepFunctionsClient,
    endpoint: str,
    manager: ResumableSourceManager[AwsStepFunctionsResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    state = manager.load_state() if manager.can_resume() else None
    state = state or AwsStepFunctionsResumeConfig()
    while True:
        rows: list[dict[str, Any]] = []
        if not state.machine_arns:
            if state.machines_done:
                break
            page = client.page("state_machines", state.machine_token)
            machines = page["stateMachines"]
            state = replace(state, machine_token=page.get("nextToken"), machines_done=not page.get("nextToken"))
            if endpoint == "state_machines":
                rows = [normalize_row(item) for item in machines]
            else:
                state = replace(
                    state, machine_arns=[item["stateMachineArn"] for item in machines if item["type"] == "STANDARD"]
                )
        elif state.execution_arns:
            execution_arn = state.execution_arns[0]
            page = client.page(
                "execution_history",
                state.history_token,
                executionArn=execution_arn,
                includeExecutionData=False,
                reverseOrder=False,
            )
            rows = [
                normalize_row({**item, "executionArn": execution_arn, "stateMachineArn": state.machine_arns[0]})
                for item in page["events"]
            ]
            token = page.get("nextToken")
            state = replace(
                state,
                history_token=token,
                execution_arns=state.execution_arns if token else state.execution_arns[1:],
            )
        elif state.executions_done:
            state = replace(state, machine_arns=state.machine_arns[1:], execution_token=None, executions_done=False)
        else:
            page = client.page("executions", state.execution_token, stateMachineArn=state.machine_arns[0])
            state = replace(state, execution_token=page.get("nextToken"), executions_done=not page.get("nextToken"))
            if endpoint == "executions":
                rows = [normalize_row(item) for item in page["executions"]]
            else:
                state = replace(state, execution_arns=[item["executionArn"] for item in page["executions"]])
        manager.save_state(state)
        if rows:
            yield rows
        manager.safe_point()


def aws_step_functions_source(
    config: AwsStepFunctionsSourceConfig,
    endpoint: str,
    api_version: str,
    manager: ResumableSourceManager[AwsStepFunctionsResumeConfig],
) -> SourceResponse:
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown AWS Step Functions table: {endpoint}")

    def items() -> Iterator[list[dict[str, Any]]]:
        client = AwsStepFunctionsClient(config, api_version)
        try:
            yield from get_rows(client, endpoint, manager)
        finally:
            client.close()

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=list(ENDPOINTS[endpoint].primary_keys),
        sort_mode=None,
        on_complete=manager.clear_state,
    )


def probe(client: AwsStepFunctionsClient, schema_name: str | None) -> None:
    page = client.request("ListStateMachines", {"maxResults": 1})
    if schema_name is None or schema_name == "state_machines":
        return
    while True:
        for machine in page["stateMachines"]:
            if machine["type"] != "STANDARD":
                continue
            executions = client.request(
                "ListExecutions", {"stateMachineArn": machine["stateMachineArn"], "maxResults": 1}
            )
            if schema_name == "executions":
                return
            while True:
                if executions["executions"]:
                    client.request(
                        "GetExecutionHistory",
                        {
                            "executionArn": executions["executions"][0]["executionArn"],
                            "maxResults": 1,
                            "includeExecutionData": False,
                            "reverseOrder": False,
                        },
                    )
                    return
                if not executions.get("nextToken"):
                    break
                executions = client.request(
                    "ListExecutions",
                    {
                        "stateMachineArn": machine["stateMachineArn"],
                        "maxResults": 1,
                        "nextToken": executions["nextToken"],
                    },
                )
        if not page.get("nextToken"):
            return
        page = client.request("ListStateMachines", {"maxResults": 1, "nextToken": page["nextToken"]})


def validate_credentials(
    config: AwsStepFunctionsSourceConfig, schema_name: str | None, api_version: str
) -> tuple[bool, str | None]:
    if schema_name is not None and schema_name not in ENDPOINTS:
        return False, f"Unknown AWS Step Functions table: {schema_name}"
    try:
        client = AwsStepFunctionsClient(config, api_version)
    except ValueError as error:
        return False, str(error)
    try:
        probe(client, schema_name)
    except AwsStepFunctionsError as error:
        if schema_name is None and error.code in {"AccessDenied", "AccessDeniedException"}:
            return True, None
        if error.code in ERROR_MESSAGES:
            return False, ERROR_MESSAGES[error.code]
        raise
    finally:
        client.close()
    return True, None
