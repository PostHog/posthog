import json
from collections.abc import Generator, Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_step_functions.aws_step_functions import (
    AwsStepFunctionsClient,
    AwsStepFunctionsError,
    AwsStepFunctionsResumeConfig,
    aws_step_functions_source,
    normalize_row,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_step_functions.settings import API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_step_functions.source import (
    AwsStepFunctionsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsstepfunctions import (
    AwsStepFunctionsSourceConfig,
)

SM1 = "arn:aws:states:us-east-1:123456789012:stateMachine:example-one"
SM2 = "arn:aws:states:us-east-1:123456789012:stateMachine:example-two"
EXPRESS = "arn:aws:states:us-east-1:123456789012:stateMachine:example-express"
EXECUTIONS = [f"arn:aws:states:us-east-1:123456789012:execution:example-one:run-{i}" for i in range(4)]
ALIASES = [f"{SM1}:alias-{i}" for i in range(2)] + [f"{SM2}:alias-0"]
MAP_RUNS = [f"arn:aws:states:us-east-1:123456789012:mapRun:example-one/map:run-{i}" for i in range(2)]
DELETED_ALIAS = f"{SM2}:alias-deleted"
DELETED_MAP_RUN = "arn:aws:states:us-east-1:123456789012:mapRun:example-two/map:run-deleted"


@pytest.fixture
def config() -> AwsStepFunctionsSourceConfig:
    return AwsStepFunctionsSourceConfig(
        aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="example-secret", region="us-east-1"
    )


@pytest.fixture
def session() -> Iterator[MagicMock]:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.aws_step_functions.aws_step_functions.make_tracked_session"
    ) as factory:
        yield factory.return_value


def response(status: int, body: object, headers: dict[str, str] | None = None) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    result.headers.update(headers or {})
    return result


def manager(state: AwsStepFunctionsResumeConfig | None = None) -> MagicMock:
    result = MagicMock()
    result.can_resume.return_value = state is not None
    result.load_state.return_value = state
    return result


def source_items(source: SourceResponse) -> Generator[list[dict[str, Any]]]:
    return cast(Generator[list[dict[str, Any]]], source.items())


@pytest.mark.parametrize(
    "region,suffix",
    [("us-east-1", "amazonaws.com"), ("eu-west-1", "amazonaws.com"), ("cn-north-1", "amazonaws.com.cn")],
)
@pytest.mark.parametrize("token", [None, "example-session-token"])
def test_signed_request(config: AwsStepFunctionsSourceConfig, region: str, suffix: str, token: str | None) -> None:
    config.region = region
    config.aws_session_token = token
    with scripted_network([ScriptedResponse(json={"stateMachines": []})]) as network:
        client = AwsStepFunctionsClient(config, API_VERSION)
        assert client.request("ListStateMachines", {"maxResults": 1}) == {"stateMachines": []}
        client.close()
    request = network.requests_log[0]
    assert len(network.requests_log) == 1
    assert request.url == f"https://states.{region}.{suffix}/"
    assert request.json() == {"maxResults": 1}
    assert request.headers["x-amz-target"] == "AWSStepFunctions.ListStateMachines"
    assert request.headers["content-type"] == "application/x-amz-json-1.0"
    assert f"/{region}/states/aws4_request" in request.headers["authorization"]
    assert "x-amz-target" in request.headers["authorization"]
    assert request.headers.get("x-amz-security-token") == token
    assert request.headers["x-amz-date"]
    assert request.read_timeout == 60


def install_pages(session: MagicMock) -> None:
    def post(url: str, **kwargs: Any) -> requests.Response:
        payload = json.loads(kwargs["data"])
        operation = kwargs["headers"]["X-Amz-Target"].split(".")[-1]
        assert payload.get("maxResults", 0) <= 1000
        assert not {"startDate", "startTime", "updatedAt", "statusFilter"}.intersection(payload)
        token = payload.get("nextToken")
        if operation == "ListStateMachines":
            machine_pages: dict[str | None, dict[str, Any]] = {
                None: {
                    "stateMachines": [
                        {"stateMachineArn": EXPRESS, "type": "EXPRESS"},
                        {"stateMachineArn": SM1, "type": "STANDARD"},
                    ],
                    "nextToken": "m2",
                },
                "m2": {"stateMachines": [], "nextToken": "m3"},
                "m3": {"stateMachines": [{"stateMachineArn": SM2, "type": "STANDARD"}]},
            }
            return response(200, machine_pages[token])
        if operation == "ListActivities":
            activity_pages: dict[str | None, dict[str, Any]] = {
                None: {
                    "activities": [{"activityArn": "a0", "creationDate": 1}, {"activityArn": "a1"}],
                    "nextToken": "a2",
                },
                "a2": {"activities": [{"activityArn": "a2"}]},
            }
            return response(200, activity_pages[token])
        if operation == "ListStateMachineVersions":
            version_pages: dict[tuple[str, str | None], dict[str, Any]] = {
                (EXPRESS, None): {"stateMachineVersions": [{"stateMachineVersionArn": f"{EXPRESS}:1"}]},
                (SM1, None): {"stateMachineVersions": [{"stateMachineVersionArn": f"{SM1}:1"}], "nextToken": "v2"},
                (SM1, "v2"): {"stateMachineVersions": [{"stateMachineVersionArn": f"{SM1}:2"}]},
                (SM2, None): {"stateMachineVersions": []},
            }
            return response(200, version_pages[(payload["stateMachineArn"], token)])
        if operation == "ListStateMachineAliases":
            alias_pages: dict[tuple[str, str | None], dict[str, Any]] = {
                (EXPRESS, None): {"stateMachineAliases": []},
                (SM1, None): {"stateMachineAliases": [{"stateMachineAliasArn": ALIASES[0]}], "nextToken": "l2"},
                (SM1, "l2"): {"stateMachineAliases": [{"stateMachineAliasArn": ALIASES[1]}]},
                (SM2, None): {
                    "stateMachineAliases": [
                        {"stateMachineAliasArn": DELETED_ALIAS},
                        {"stateMachineAliasArn": ALIASES[2]},
                    ]
                },
            }
            return response(200, alias_pages[(payload["stateMachineArn"], token)])
        if operation == "DescribeStateMachineAlias":
            alias_arn = payload["stateMachineAliasArn"]
            if alias_arn == DELETED_ALIAS:
                return response(400, {"__type": "ResourceNotFound", "message": "Example missing alias"})
            return response(
                200,
                {
                    "stateMachineAliasArn": alias_arn,
                    "routingConfiguration": [{"stateMachineVersionArn": f"{SM1}:1", "weight": 100}],
                    "updateDate": 5,
                },
            )
        if operation == "ListMapRuns":
            map_run_pages: dict[tuple[str, str | None], dict[str, Any]] = {
                (EXECUTIONS[0], None): {"mapRuns": [{"mapRunArn": MAP_RUNS[0]}], "nextToken": "r2"},
                (EXECUTIONS[0], "r2"): {"mapRuns": []},
                (EXECUTIONS[2], None): {"mapRuns": [{"mapRunArn": MAP_RUNS[1]}]},
                (EXECUTIONS[3], None): {"mapRuns": [{"mapRunArn": DELETED_MAP_RUN}]},
            }
            return response(200, map_run_pages.get((payload["executionArn"], token), {"mapRuns": []}))
        if operation == "DescribeMapRun":
            if payload["mapRunArn"] == DELETED_MAP_RUN:
                return response(400, {"__type": "ResourceNotFound", "message": "Example missing map run"})
            return response(
                200,
                {
                    "mapRunArn": payload["mapRunArn"],
                    "executionArn": EXECUTIONS[0],
                    "startDate": 10,
                    "itemCounts": {"failed": 1, "total": 3},
                },
            )
        if operation == "ListExecutions" and "mapRunArn" in payload:
            assert "stateMachineArn" not in payload
            child_pages: dict[tuple[str, str | None], dict[str, Any]] = {
                (MAP_RUNS[0], None): {
                    "executions": [{"executionArn": f"{MAP_RUNS[0]}:child-{i}"} for i in range(2)],
                    "nextToken": "c2",
                },
                (MAP_RUNS[0], "c2"): {"executions": [{"executionArn": f"{MAP_RUNS[0]}:child-2"}]},
                (MAP_RUNS[1], None): {"executions": []},
                (DELETED_MAP_RUN, None): {"executions": []},
            }
            return response(200, child_pages[(payload["mapRunArn"], token)])
        if operation == "ListExecutions":
            machine = payload["stateMachineArn"]
            assert machine != EXPRESS
            execution_pages: dict[tuple[str, str | None], dict[str, Any]] = {
                (SM1, None): {
                    "executions": [
                        {"executionArn": arn, "stateMachineArn": SM1, "startDate": 100} for arn in EXECUTIONS[:2]
                    ],
                    "nextToken": "e2",
                },
                (SM1, "e2"): {"executions": [{"executionArn": EXECUTIONS[2], "stateMachineArn": SM1, "startDate": 1}]},
                (SM2, None): {"executions": [], "nextToken": "e-empty"},
                (SM2, "e-empty"): {
                    "executions": [{"executionArn": EXECUTIONS[3], "stateMachineArn": SM2, "startDate": 200}]
                },
            }
            return response(200, execution_pages[(machine, token)])
        assert operation == "GetExecutionHistory"
        assert payload["includeExecutionData"] is False
        assert payload["reverseOrder"] is False
        if token is None:
            return response(200, {"events": [{"id": 1, "timestamp": 1}], "nextToken": "h2"})
        assert token == "h2"
        return response(200, {"events": [{"id": 2, "previousEventId": 1, "timestamp": 2}]})

    session.post.side_effect = post


@pytest.mark.parametrize(
    "endpoint,count",
    [
        ("state_machines", 3),
        ("executions", 4),
        ("execution_history", 8),
        ("activities", 3),
        ("state_machine_versions", 3),
        ("state_machine_aliases", 3),
        ("map_runs", 2),
        ("map_run_executions", 3),
    ],
)
def test_full_refresh_pagination_and_resume_at_every_batch(
    config: AwsStepFunctionsSourceConfig, session: MagicMock, endpoint: str, count: int
) -> None:
    install_pages(session)
    initial_manager = manager()
    source = aws_step_functions_source(config, endpoint, API_VERSION, initial_manager)
    expected = [row for batch in source_items(source) for row in batch]
    assert len(expected) == count
    assert source.primary_keys is not None
    assert len({tuple(row[key] for key in source.primary_keys) for row in expected}) == count
    assert source.sort_mode is None
    initial_manager.clear_state.assert_not_called()
    assert source.on_complete is not None
    source.on_complete()
    initial_manager.clear_state.assert_called_once()
    initial_manager.safe_point.assert_called()
    if endpoint == "executions":
        assert {row["start_date"] for row in expected} == {datetime.fromtimestamp(i, UTC) for i in (1, 100, 200)}
    if endpoint == "execution_history":
        assert {row["execution_arn"] for row in expected} == set(EXECUTIONS)
        assert {row["state_machine_arn"] for row in expected} == {SM1, SM2}
    if endpoint == "state_machine_versions":
        assert {row["state_machine_arn"] for row in expected} == {EXPRESS, SM1}
    if endpoint == "state_machine_aliases":
        assert [row["state_machine_alias_arn"] for row in expected] == ALIASES
        assert [row["state_machine_arn"] for row in expected] == [SM1, SM1, SM2]
        assert {row["update_date"] for row in expected} == {datetime.fromtimestamp(5, UTC)}
    if endpoint == "map_runs":
        assert [row["map_run_arn"] for row in expected] == MAP_RUNS
        assert {row["state_machine_arn"] for row in expected} == {SM1}
        assert expected[0]["item_counts"] == {"failed": 1, "total": 3}
    if endpoint == "map_run_executions":
        assert {row["map_run_arn"] for row in expected} == {MAP_RUNS[0]}
    batch_count = len(list(source_items(aws_step_functions_source(config, endpoint, API_VERSION, manager()))))
    for stop_after in range(1, batch_count + 1):
        interrupted_manager = manager()
        iterator = source_items(aws_step_functions_source(config, endpoint, API_VERSION, interrupted_manager))
        prefix = [row for _ in range(stop_after) for row in next(iterator)]
        state = interrupted_manager.save_state.call_args.args[0]
        iterator.close()
        resumed = aws_step_functions_source(config, endpoint, API_VERSION, manager(state))
        assert prefix + [row for batch in source_items(resumed) for row in batch] == expected
    session.close.assert_called()


@pytest.mark.parametrize(
    "schema_name", [None, "state_machines", "executions", "execution_history", "activities", "state_machine_aliases"]
)
@pytest.mark.parametrize(
    "code,valid_at_create",
    [
        ("AccessDeniedException", True),
        ("AccessDenied", True),
        ("UnrecognizedClientException", False),
        ("InvalidSignatureException", False),
        ("ExpiredTokenException", False),
        ("SubscriptionRequiredException", False),
    ],
)
def test_credentials_error_mapping(
    config: AwsStepFunctionsSourceConfig, session: MagicMock, schema_name: str | None, code: str, valid_at_create: bool
) -> None:
    session.post.return_value = response(
        400, {"__type": f"com.amazonaws.states#{code}", "message": "Example AWS error"}
    )
    valid, message = validate_credentials(config, schema_name, API_VERSION)
    assert valid is (schema_name is None and valid_at_create)
    if valid:
        assert message is None
    else:
        assert message
        assert "Example AWS error" not in message
    patterns = AwsStepFunctionsSource().get_non_retryable_errors()
    assert any(pattern in f"AWS Step Functions request failed: {code} - Example AWS error" for pattern in patterns)
    session.post.assert_called_once()
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "status,body,headers,code",
    [
        (403, {}, {"x-amzn-ErrorType": "AccessDeniedException:http"}, "AccessDeniedException"),
        (500, {}, {}, "HTTP 500"),
        (400, [], {}, "HTTP 400"),
        (302, {}, {"Location": "https://example.com/redirect"}, "HTTP 302"),
    ],
)
def test_transport_errors(
    config: AwsStepFunctionsSourceConfig,
    status: int,
    body: object,
    headers: dict[str, str],
    code: str,
) -> None:
    with scripted_network(always(ScriptedResponse(status=status, json=body, headers=headers))) as network:
        client = AwsStepFunctionsClient(config, API_VERSION)
        with pytest.raises(AwsStepFunctionsError) as error:
            client.request("ListStateMachines", {})
        client.close()
    assert error.value.code == code
    assert {request.path for request in network.requests_log} == {"/"}
    assert {request.headers["x-amz-target"] for request in network.requests_log} == {
        "AWSStepFunctions.ListStateMachines"
    }


def test_body_throttle_retries_with_a_new_signature(config: AwsStepFunctionsSourceConfig) -> None:
    with scripted_network(
        [
            ScriptedResponse(status=400, json={"__type": "ThrottlingException"}),
            ScriptedResponse(json={"stateMachines": []}),
        ]
    ) as network:
        client = AwsStepFunctionsClient(config, API_VERSION)
        result = client.request("ListStateMachines", {})
        client.close()
    assert result == {"stateMachines": []}
    assert len(network.requests_log) == 2
    assert all(request.headers["authorization"].startswith("AWS4-HMAC-SHA256 ") for request in network.requests_log)
    assert all(request.headers["x-amz-date"] for request in network.requests_log)


@pytest.mark.parametrize("code", ["ServiceUnavailable", "UnknownError"])
def test_validation_reports_an_unreachable_vendor_for_server_errors(
    config: AwsStepFunctionsSourceConfig, session: MagicMock, code: str
) -> None:
    session.post.return_value = response(500, {"__type": code})
    assert validate_credentials(config, None, API_VERSION) == (
        False,
        "Couldn't reach AWS Step Functions to check your credentials. Try again in a few minutes.",
    )
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("region", "us-east-1.example.com", "AWS region"),
        ("region", "", "AWS region"),
        ("aws_access_key_id", "", "access key ID"),
        ("aws_secret_access_key", "", "secret access key"),
    ],
)
def test_invalid_config_does_not_send_credentials(
    config: AwsStepFunctionsSourceConfig, field: str, value: str, message: str
) -> None:
    setattr(config, field, value)
    with scripted_network([]) as network:
        valid, reason = validate_credentials(config, None, API_VERSION)
    assert not valid
    assert reason is not None and message in reason
    assert network.requests_log == []


@pytest.mark.parametrize(
    "schema_name,answers,last_call",
    [
        (None, [], ("ListStateMachines", {"maxResults": 1})),
        ("state_machines", [], ("ListStateMachines", {"maxResults": 1})),
        (
            "executions",
            [{"executions": [{"executionArn": EXECUTIONS[0]}]}],
            ("ListExecutions", {"stateMachineArn": SM1, "maxResults": 1}),
        ),
        (
            "execution_history",
            [{"executions": [{"executionArn": EXECUTIONS[0]}]}, {"events": [{"id": 1}]}],
            (
                "GetExecutionHistory",
                {"executionArn": EXECUTIONS[0], "maxResults": 1, "includeExecutionData": False, "reverseOrder": False},
            ),
        ),
        (
            "state_machine_versions",
            [{"stateMachineVersions": []}],
            ("ListStateMachineVersions", {"stateMachineArn": EXPRESS, "maxResults": 1}),
        ),
        (
            "state_machine_aliases",
            [
                {"stateMachineAliases": []},
                {"stateMachineAliases": [{"stateMachineAliasArn": ALIASES[0]}]},
                {"stateMachineAliasArn": ALIASES[0]},
            ],
            ("DescribeStateMachineAlias", {"stateMachineAliasArn": ALIASES[0]}),
        ),
        (
            "map_runs",
            [
                {"executions": [{"executionArn": EXECUTIONS[0]}], "nextToken": "e2"},
                {"mapRuns": []},
                {"executions": [{"executionArn": EXECUTIONS[1]}]},
                {"mapRuns": [{"mapRunArn": MAP_RUNS[0]}]},
                {"mapRunArn": MAP_RUNS[0]},
            ],
            ("DescribeMapRun", {"mapRunArn": MAP_RUNS[0]}),
        ),
        (
            "map_run_executions",
            [
                {"executions": [{"executionArn": EXECUTIONS[0]}]},
                {"mapRuns": [{"mapRunArn": MAP_RUNS[0]}]},
                {"executions": []},
            ],
            ("ListExecutions", {"mapRunArn": MAP_RUNS[0], "maxResults": 1}),
        ),
        (
            "map_run_executions",
            [{"executions": [{"executionArn": EXECUTIONS[0]}]}, {"mapRuns": []}, {"stateMachines": []}],
            ("ListStateMachines", {"maxResults": 1, "nextToken": "m2"}),
        ),
    ],
)
def test_permission_probe_walks_to_the_table_operation(
    config: AwsStepFunctionsSourceConfig,
    schema_name: str | None,
    answers: list[dict[str, Any]],
    last_call: tuple[str, dict[str, Any]],
) -> None:
    machines = {
        "stateMachines": [
            {"stateMachineArn": EXPRESS, "type": "EXPRESS"},
            {"stateMachineArn": SM1, "type": "STANDARD"},
        ],
        "nextToken": "m2",
    }
    with scripted_network([ScriptedResponse(json=body) for body in [machines, *answers]]) as network:
        assert validate_credentials(config, schema_name, API_VERSION) == (True, None)
    calls = network.requests_log
    assert len(calls) == len(answers) + 1
    assert (calls[-1].headers["x-amz-target"].split(".")[-1], calls[-1].json()) == last_call


def test_activities_probe_skips_state_machines(config: AwsStepFunctionsSourceConfig) -> None:
    with scripted_network([ScriptedResponse(json={"activities": []})]) as network:
        assert validate_credentials(config, "activities", API_VERSION) == (True, None)
    assert [request.headers["x-amz-target"] for request in network.requests_log] == ["AWSStepFunctions.ListActivities"]


@pytest.mark.parametrize("schema_name", ["executions", "execution_history", "map_runs"])
def test_probe_handles_empty_and_express_only_accounts(config: AwsStepFunctionsSourceConfig, schema_name: str) -> None:
    with scripted_network(
        [
            ScriptedResponse(
                json={"stateMachines": [{"stateMachineArn": EXPRESS, "type": "EXPRESS"}], "nextToken": "next"}
            ),
            ScriptedResponse(json={"stateMachines": []}),
        ]
    ) as network:
        assert validate_credentials(config, schema_name, API_VERSION) == (True, None)
    assert len(network.requests_log) == 2
    assert [request.json().get("nextToken") for request in network.requests_log] == [None, "next"]


def test_unknown_schema_and_version_fail_before_network(config: AwsStepFunctionsSourceConfig) -> None:
    with scripted_network([]) as network:
        assert validate_credentials(config, "missing", API_VERSION) == (
            False,
            "Unknown AWS Step Functions table: missing",
        )
    assert network.requests_log == []

    driver = SourceDriver(AwsStepFunctionsSource(), config)
    missing = driver.run("missing", [])
    assert isinstance(missing.raised, ValueError)
    assert "Unknown AWS Step Functions table" in str(missing.raised)
    assert missing.requests == []

    unsupported = driver.run("state_machines", [], api_version="1900-01-01")
    assert isinstance(unsupported.raised, ValueError)
    assert "Unsupported AWS Step Functions API version" in str(unsupported.raised)
    assert unsupported.requests == []


def test_normalization_preserves_nested_details() -> None:
    details = {"error": "ExampleError", "cause": "Example task failure"}
    assert normalize_row(
        {"executionArn": "example", "timestamp": 1.5, "stopDate": None, "taskFailedEventDetails": details}
    ) == {
        "execution_arn": "example",
        "timestamp": datetime.fromtimestamp(1.5, UTC),
        "stop_date": None,
        "task_failed_event_details": details,
    }
