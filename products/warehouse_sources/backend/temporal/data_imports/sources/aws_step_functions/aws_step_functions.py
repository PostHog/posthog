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
    MACHINE_CHILD_ENDPOINTS,
    MAP_RUN_ENDPOINTS,
    PAGE_SIZE,
    PROBE_PARENT_LIMIT,
    TARGET_PREFIXES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import probe_status_message
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsstepfunctions import (
    AwsStepFunctionsSourceConfig,
)


class AwsStepFunctionsError(Exception):
    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        self.code = code
        self.status_code = status_code
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
    child_token: str | None = None
    children_done: bool = False
    alias_arns: list[str] = field(default_factory=list)
    map_run_token: str | None = None
    map_run_arns: list[str] = field(default_factory=list)
    map_runs_done: bool = False
    map_run_execution_token: str | None = None
    activity_token: str | None = None
    activities_done: bool = False


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
            raise error_class(code, message, response.status_code)
        if response.status_code != 200:
            raise AwsStepFunctionsError(
                f"HTTP {response.status_code}", "Unexpected AWS response status.", response.status_code
            )
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("AWS Step Functions returned an invalid response.")
        return result

    def page(self, endpoint: str, token: str | None = None, **params: Any) -> dict[str, Any]:
        payload = {"maxResults": PAGE_SIZE, **params}
        if token:
            payload["nextToken"] = token
        return self.request(ENDPOINTS[endpoint].operation, payload)

    def describe(self, operation: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        # A resource listed earlier in the walk can be deleted before its describe call.
        try:
            return self.request(operation, payload)
        except AwsStepFunctionsError as error:
            if error.code == "ResourceNotFound":
                return None
            raise

    def close(self) -> None:
        self.session.close()


def normalize_row(item: dict[str, Any]) -> dict[str, Any]:
    row = {re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key).lower(): value for key, value in item.items()}
    for key in ("creation_date", "update_date", "start_date", "stop_date", "redrive_date", "timestamp"):
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
        if endpoint == "activities":
            if state.activities_done:
                break
            page = client.page("activities", state.activity_token)
            rows = [normalize_row(item) for item in page["activities"]]
            state = replace(state, activity_token=page.get("nextToken"), activities_done=not page.get("nextToken"))
        elif not state.machine_arns:
            if state.machines_done:
                break
            page = client.page("state_machines", state.machine_token)
            machines = page["stateMachines"]
            state = replace(state, machine_token=page.get("nextToken"), machines_done=not page.get("nextToken"))
            if endpoint == "state_machines":
                rows = [normalize_row(item) for item in machines]
            else:
                # Versions and aliases exist for Express machines too; only Standard executions can be listed.
                state = replace(
                    state,
                    machine_arns=[
                        item["stateMachineArn"]
                        for item in machines
                        if endpoint in MACHINE_CHILD_ENDPOINTS or item["type"] == "STANDARD"
                    ],
                )
        elif endpoint in MACHINE_CHILD_ENDPOINTS:
            machine_arn = state.machine_arns[0]
            if state.alias_arns:
                alias = client.describe("DescribeStateMachineAlias", {"stateMachineAliasArn": state.alias_arns[0]})
                rows = [normalize_row({**alias, "stateMachineArn": machine_arn})] if alias else []
                state = replace(state, alias_arns=state.alias_arns[1:])
            elif state.children_done:
                state = replace(state, machine_arns=state.machine_arns[1:], child_token=None, children_done=False)
            else:
                page = client.page(endpoint, state.child_token, stateMachineArn=machine_arn)
                items = page[ENDPOINTS[endpoint].result_key]
                state = replace(state, child_token=page.get("nextToken"), children_done=not page.get("nextToken"))
                if endpoint == "state_machine_versions":
                    rows = [normalize_row({**item, "stateMachineArn": machine_arn}) for item in items]
                else:
                    state = replace(state, alias_arns=[item["stateMachineAliasArn"] for item in items])
        elif state.execution_arns and endpoint in MAP_RUN_ENDPOINTS:
            if state.map_run_arns:
                map_run_arn = state.map_run_arns[0]
                if endpoint == "map_runs":
                    map_run = client.describe("DescribeMapRun", {"mapRunArn": map_run_arn})
                    rows = [normalize_row({**map_run, "stateMachineArn": state.machine_arns[0]})] if map_run else []
                    state = replace(state, map_run_arns=state.map_run_arns[1:])
                else:
                    page = client.page("map_run_executions", state.map_run_execution_token, mapRunArn=map_run_arn)
                    rows = [normalize_row({**item, "mapRunArn": map_run_arn}) for item in page["executions"]]
                    token = page.get("nextToken")
                    state = replace(
                        state,
                        map_run_execution_token=token,
                        map_run_arns=state.map_run_arns if token else state.map_run_arns[1:],
                    )
            elif state.map_runs_done:
                state = replace(state, execution_arns=state.execution_arns[1:], map_run_token=None, map_runs_done=False)
            else:
                page = client.page("map_runs", state.map_run_token, executionArn=state.execution_arns[0])
                state = replace(
                    state,
                    map_run_token=page.get("nextToken"),
                    map_runs_done=not page.get("nextToken"),
                    map_run_arns=[item["mapRunArn"] for item in page["mapRuns"]],
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


def probe_machine_children(client: AwsStepFunctionsClient, schema_name: str, machine_arn: str) -> bool:
    page = client.request(ENDPOINTS[schema_name].operation, {"stateMachineArn": machine_arn, "maxResults": 1})
    if schema_name == "state_machine_versions":
        return True
    if not page["stateMachineAliases"]:
        return False
    client.describe(
        "DescribeStateMachineAlias", {"stateMachineAliasArn": page["stateMachineAliases"][0]["stateMachineAliasArn"]}
    )
    return True


def probe_map_runs(client: AwsStepFunctionsClient, schema_name: str, execution_arn: str) -> bool:
    page = client.request("ListMapRuns", {"executionArn": execution_arn, "maxResults": 1})
    if not page["mapRuns"]:
        return False
    map_run_arn = page["mapRuns"][0]["mapRunArn"]
    if schema_name == "map_runs":
        client.describe("DescribeMapRun", {"mapRunArn": map_run_arn})
    else:
        client.request("ListExecutions", {"mapRunArn": map_run_arn, "maxResults": 1})
    return True


def probe(client: AwsStepFunctionsClient, schema_name: str | None) -> None:
    if schema_name == "activities":
        client.request("ListActivities", {"maxResults": 1})
        return
    page = client.request("ListStateMachines", {"maxResults": 1})
    if schema_name is None or schema_name == "state_machines":
        return
    parents_checked = 0
    while True:
        for machine in page["stateMachines"]:
            if schema_name in MACHINE_CHILD_ENDPOINTS:
                parents_checked += 1
                if (
                    probe_machine_children(client, schema_name, machine["stateMachineArn"])
                    or parents_checked >= PROBE_PARENT_LIMIT
                ):
                    return
                continue
            if machine["type"] != "STANDARD":
                continue
            executions = client.request(
                "ListExecutions", {"stateMachineArn": machine["stateMachineArn"], "maxResults": 1}
            )
            if schema_name == "executions":
                return
            while True:
                if executions["executions"]:
                    execution_arn = executions["executions"][0]["executionArn"]
                    if schema_name in MAP_RUN_ENDPOINTS:
                        parents_checked += 1
                        if probe_map_runs(client, schema_name, execution_arn) or parents_checked >= PROBE_PARENT_LIMIT:
                            return
                    else:
                        client.request(
                            "GetExecutionHistory",
                            {
                                "executionArn": execution_arn,
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
        status_message = probe_status_message("AWS Step Functions", error.status_code)
        if status_message:
            return False, status_message
        raise
    finally:
        client.close()
    return True, None
