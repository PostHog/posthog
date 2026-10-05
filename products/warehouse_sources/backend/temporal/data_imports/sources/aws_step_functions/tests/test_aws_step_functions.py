import json
from collections.abc import Generator, Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from tenacity import wait_none

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsstepfunctions import (
    AwsStepFunctionsSourceConfig,
)

SM1 = "arn:aws:states:us-east-1:123456789012:stateMachine:example-one"
SM2 = "arn:aws:states:us-east-1:123456789012:stateMachine:example-two"
EXPRESS = "arn:aws:states:us-east-1:123456789012:stateMachine:example-express"
EXECUTIONS = [f"arn:aws:states:us-east-1:123456789012:execution:example-one:run-{i}" for i in range(4)]


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
def test_signed_request(
    config: AwsStepFunctionsSourceConfig, session: MagicMock, region: str, suffix: str, token: str | None
) -> None:
    config.region = region
    config.aws_session_token = token
    session.post.return_value = response(200, {"stateMachines": []})
    client = AwsStepFunctionsClient(config, API_VERSION)
    client.request("ListStateMachines", {"maxResults": 1})
    args, kwargs = session.post.call_args
    assert args == (f"https://states.{region}.{suffix}/",)
    assert json.loads(kwargs["data"]) == {"maxResults": 1}
    headers = kwargs["headers"]
    assert headers["X-Amz-Target"] == "AWSStepFunctions.ListStateMachines"
    assert headers["Content-Type"] == "application/x-amz-json-1.0"
    assert f"/{region}/states/aws4_request" in headers["Authorization"]
    assert "x-amz-target" in headers["Authorization"]
    assert headers.get("X-Amz-Security-Token") == token
    assert headers["X-Amz-Date"]
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == 60


def install_pages(session: MagicMock) -> None:
    def post(url: str, **kwargs: Any) -> requests.Response:
        payload = json.loads(kwargs["data"])
        operation = kwargs["headers"]["X-Amz-Target"].split(".")[-1]
        assert payload["maxResults"] <= 1000
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


@pytest.mark.parametrize("endpoint,count", [("state_machines", 3), ("executions", 4), ("execution_history", 8)])
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


@pytest.mark.parametrize("endpoint", ["state_machines", "executions", "execution_history"])
def test_empty_pages_finish_and_resume_without_requests(
    config: AwsStepFunctionsSourceConfig, session: MagicMock, endpoint: str
) -> None:
    session.post.side_effect = [
        response(200, {"stateMachines": [], "nextToken": "next"}),
        response(200, {"stateMachines": []}),
    ]
    checkpoint = manager()
    assert list(source_items(aws_step_functions_source(config, endpoint, API_VERSION, checkpoint))) == []
    assert checkpoint.safe_point.call_count == 2
    state = checkpoint.save_state.call_args.args[0]
    session.post.reset_mock()
    assert list(source_items(aws_step_functions_source(config, endpoint, API_VERSION, manager(state)))) == []
    session.post.assert_not_called()


@pytest.mark.parametrize("schema_name", [None, "state_machines", "executions", "execution_history"])
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
        (302, {}, {}, "HTTP 302"),
    ],
)
def test_transport_errors(
    config: AwsStepFunctionsSourceConfig,
    session: MagicMock,
    status: int,
    body: object,
    headers: dict[str, str],
    code: str,
) -> None:
    session.post.return_value = response(status, body, headers)
    with pytest.raises(AwsStepFunctionsError) as error:
        AwsStepFunctionsClient(config, API_VERSION).request("ListStateMachines", {})
    assert error.value.code == code
    session.post.assert_called_once()


def test_body_throttle_retries_with_a_new_signature(config: AwsStepFunctionsSourceConfig, session: MagicMock) -> None:
    session.post.side_effect = [response(400, {"__type": "ThrottlingException"}), response(200, {"stateMachines": []})]
    client = AwsStepFunctionsClient(config, API_VERSION)
    with patch.object(client.signer, "add_auth", wraps=client.signer.add_auth) as sign:
        result = client.request.retry_with(wait=wait_none())(client, "ListStateMachines", {})  # type: ignore[attr-defined]
    assert result == {"stateMachines": []}
    assert sign.call_count == 2


@pytest.mark.parametrize("code", ["ServiceUnavailable", "UnknownError"])
def test_validation_propagates_transient_and_unknown_errors(
    config: AwsStepFunctionsSourceConfig, session: MagicMock, code: str
) -> None:
    session.post.return_value = response(500, {"__type": code})
    with pytest.raises(AwsStepFunctionsError):
        validate_credentials(config, None, API_VERSION)
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
    config: AwsStepFunctionsSourceConfig, session: MagicMock, field: str, value: str, message: str
) -> None:
    setattr(config, field, value)
    valid, reason = validate_credentials(config, None, API_VERSION)
    assert not valid
    assert reason is not None and message in reason
    session.post.assert_not_called()


@pytest.mark.parametrize("schema_name", [None, "state_machines", "executions", "execution_history"])
def test_permission_probe_walks_to_standard_execution(
    config: AwsStepFunctionsSourceConfig, session: MagicMock, schema_name: str | None
) -> None:
    install_pages(session)
    assert validate_credentials(config, schema_name, API_VERSION) == (True, None)
    calls = session.post.call_args_list
    if schema_name in (None, "state_machines"):
        assert len(calls) == 1
    elif schema_name == "executions":
        assert calls[-1].kwargs["headers"]["X-Amz-Target"].endswith(".ListExecutions")
    else:
        assert calls[-1].kwargs["headers"]["X-Amz-Target"].endswith(".GetExecutionHistory")


@pytest.mark.parametrize("schema_name", ["executions", "execution_history"])
def test_probe_handles_empty_and_express_only_accounts(
    config: AwsStepFunctionsSourceConfig, session: MagicMock, schema_name: str
) -> None:
    session.post.side_effect = [
        response(200, {"stateMachines": [{"stateMachineArn": EXPRESS, "type": "EXPRESS"}], "nextToken": "next"}),
        response(200, {"stateMachines": []}),
    ]
    assert validate_credentials(config, schema_name, API_VERSION) == (True, None)
    assert len(session.post.call_args_list) == 2


def test_unknown_schema_and_version_fail_before_network(
    config: AwsStepFunctionsSourceConfig, session: MagicMock
) -> None:
    assert validate_credentials(config, "missing", API_VERSION) == (False, "Unknown AWS Step Functions table: missing")
    with pytest.raises(ValueError, match="Unknown AWS Step Functions table"):
        aws_step_functions_source(config, "missing", API_VERSION, manager())
    with pytest.raises(ValueError, match="Unsupported AWS Step Functions API version"):
        AwsStepFunctionsClient(config, "1900-01-01")
    session.post.assert_not_called()


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
