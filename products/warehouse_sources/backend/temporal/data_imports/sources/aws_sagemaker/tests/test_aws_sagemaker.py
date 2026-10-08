import json
import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_sagemaker.aws_sagemaker import (
    TRANSPORT_RETRY,
    AwsSagemakerClient,
    AwsSagemakerError,
    AwsSagemakerResumeConfig,
    AwsSagemakerThrottledError,
    aws_sagemaker_source,
    error_for_response,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssagemaker import (
    AwsSagemakerSourceConfig,
)


@pytest.fixture
def config() -> AwsSagemakerSourceConfig:
    return AwsSagemakerSourceConfig(
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="fake-secret",
        aws_session_token="fake-session",
        region="eu-west-1",
    )


@pytest.fixture
def transport() -> Iterator[MagicMock]:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.aws_sagemaker.aws_sagemaker.make_tracked_session"
    ) as factory:
        yield factory.return_value


def response(body: dict[str, object], status: int = 200, header: str | None = None) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    if header:
        result.headers["x-amzn-ErrorType"] = header
    return result


def manager(state: AwsSagemakerResumeConfig | None = None) -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.load_state.return_value = state
    return result


@pytest.mark.parametrize(
    "region,host",
    [
        ("eu-west-1", "api.sagemaker.eu-west-1.amazonaws.com"),
        ("cn-north-1", "api.sagemaker.cn-north-1.amazonaws.com.cn"),
        ("us-gov-west-1", "api.sagemaker.us-gov-west-1.amazonaws.com"),
    ],
)
@pytest.mark.parametrize("session_token", [None, "fake-session"])
def test_signed_json_request(
    config: AwsSagemakerSourceConfig, transport: MagicMock, region: str, host: str, session_token: str | None
) -> None:
    config.region = region
    config.aws_session_token = session_token
    transport.post.return_value = response({"Models": []})
    client = AwsSagemakerClient(config, "2017-07-24")
    assert client.request("ListModels", {"MaxResults": 1}) == {"Models": []}
    args, kwargs = transport.post.call_args
    assert args == (f"https://{host}/",)
    assert json.loads(kwargs["data"]) == {"MaxResults": 1}
    headers = kwargs["headers"]
    assert headers["Content-Type"] == "application/x-amz-json-1.1"
    assert headers["X-Amz-Target"] == "SageMaker.ListModels"
    assert "AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/" in headers["Authorization"]
    assert f"/{region}/sagemaker/aws4_request" in headers["Authorization"]
    assert headers.get("X-Amz-Security-Token") == session_token
    assert headers["X-Amz-Date"]
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == 60


@pytest.mark.parametrize(
    "endpoint,list_operation,result_key,describe_operation,name_field,arn_field,column",
    [
        (
            "training_jobs",
            "ListTrainingJobs",
            "TrainingJobSummaries",
            "DescribeTrainingJob",
            "TrainingJobName",
            "TrainingJobArn",
            "training_job_arn",
        ),
        (
            "processing_jobs",
            "ListProcessingJobs",
            "ProcessingJobSummaries",
            "DescribeProcessingJob",
            "ProcessingJobName",
            "ProcessingJobArn",
            "processing_job_arn",
        ),
        ("endpoints", "ListEndpoints", "Endpoints", "DescribeEndpoint", "EndpointName", "EndpointArn", "endpoint_arn"),
        ("models", "ListModels", "Models", "DescribeModel", "ModelName", "ModelArn", "model_arn"),
    ],
)
def test_pagination_describes_rows_and_stages_only_complete_pages(
    config: AwsSagemakerSourceConfig,
    transport: MagicMock,
    endpoint: str,
    list_operation: str,
    result_key: str,
    describe_operation: str,
    name_field: str,
    arn_field: str,
    column: str,
) -> None:
    transport.post.side_effect = [
        response({result_key: [{name_field: "example"}], "NextToken": "second"}),
        response(
            {
                arn_field: "arn:aws:sagemaker:eu-west-1:123456789012:example/item",
                "CreationTime": 1704067200,
                "ResourceConfig": {"InstanceCount": 2},
            }
        ),
        response({result_key: [], "NextToken": "last"}),
        response({result_key: [{name_field: "other"}]}),
        response({arn_field: "arn:aws:sagemaker:eu-west-1:123456789012:example/other", "CreationTime": 1704153600}),
    ]
    resume = manager()
    resource = aws_sagemaker_source(config, endpoint, "2017-07-24", resume, False, 1700000000)
    rows = [row for batch in cast(Iterable[Any], resource.items()) for row in batch]
    assert len(rows) == 2
    assert rows[0]["creation_time"] == dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    assert rows[0]["resource_config"] == {"InstanceCount": 2}
    assert rows[0][column].endswith("example/item")
    assert resource.primary_keys == [column]
    calls = transport.post.call_args_list
    assert [call.kwargs["headers"]["X-Amz-Target"] for call in calls] == [
        f"SageMaker.{list_operation}",
        f"SageMaker.{describe_operation}",
        f"SageMaker.{list_operation}",
        f"SageMaker.{list_operation}",
        f"SageMaker.{describe_operation}",
    ]
    assert json.loads(calls[0].kwargs["data"]) == {
        "MaxResults": 100,
        "SortBy": "CreationTime",
        "SortOrder": "Ascending",
    }
    assert json.loads(calls[1].kwargs["data"]) == {name_field: "example"}
    assert json.loads(calls[2].kwargs["data"])["NextToken"] == "second"
    assert json.loads(calls[3].kwargs["data"])["NextToken"] == "last"
    assert [call.args[0] for call in resume.save_state.call_args_list] == [
        AwsSagemakerResumeConfig(next_token="second"),
        AwsSagemakerResumeConfig(next_token="last"),
        AwsSagemakerResumeConfig(complete=True),
    ]
    assert resume.safe_point.call_count == 3
    transport.close.assert_called_once()


@pytest.mark.parametrize("incremental", [True, False])
@pytest.mark.parametrize(
    "last_value",
    [1704067200, 1704067200.0, "2024-01-01T00:00:00Z", dt.datetime(2024, 1, 1), dt.datetime(2024, 1, 1, tzinfo=dt.UTC)],
)
def test_incremental_filter_and_full_refresh(
    config: AwsSagemakerSourceConfig,
    transport: MagicMock,
    incremental: bool,
    last_value: dt.datetime | str | int | float | None,
) -> None:
    transport.post.side_effect = [response({"Models": [], "NextToken": "next"}), response({"Models": []})]
    resource = aws_sagemaker_source(config, "models", "2017-07-24", manager(), incremental, last_value)
    assert list(cast(Iterable[Any], resource.items())) == []
    assert resource.sort_mode == "asc"
    for call in transport.post.call_args_list:
        payload = json.loads(call.kwargs["data"])
        assert payload.get("CreationTimeAfter") == (1704067200.0 if incremental else None)
        assert payload["SortOrder"] == "Ascending"


def test_resume_preserves_original_filter(config: AwsSagemakerSourceConfig, transport: MagicMock) -> None:
    resume = manager(AwsSagemakerResumeConfig(next_token="resume", watermark=1704067200.0))
    transport.post.return_value = response({"Models": []})
    assert list(get_rows(config, "models", "2017-07-24", resume, True, 1705000000)) == []
    payload = json.loads(transport.post.call_args.kwargs["data"])
    assert payload["NextToken"] == "resume"
    assert payload["CreationTimeAfter"] == 1704067200.0


def test_complete_resume_makes_no_request(config: AwsSagemakerSourceConfig, transport: MagicMock) -> None:
    assert (
        list(get_rows(config, "models", "2017-07-24", manager(AwsSagemakerResumeConfig(complete=True)), True, None))
        == []
    )
    transport.post.assert_not_called()


@pytest.mark.parametrize("failure", ["describe", "repeated_token", "missing_arn"])
def test_failed_page_does_not_advance_resume(
    config: AwsSagemakerSourceConfig, transport: MagicMock, failure: str
) -> None:
    resume = manager(AwsSagemakerResumeConfig(next_token="current"))
    if failure == "repeated_token":
        transport.post.return_value = response({"Models": [], "NextToken": "current"})
    else:
        transport.post.side_effect = [
            response({"Models": [{"ModelName": "example"}], "NextToken": "next"}),
            response({"__type": "AccessDeniedException"}, 400)
            if failure == "describe"
            else response({"ModelName": "example"}),
        ]
    with pytest.raises((AwsSagemakerError, ValueError)):
        list(get_rows(config, "models", "2017-07-24", resume, False, None))
    resume.save_state.assert_not_called()
    transport.close.assert_called_once()


@pytest.mark.parametrize(
    "status,code,throttled",
    [
        (400, "ThrottlingException", True),
        (429, "ThrottlingException", False),
        (503, "ServiceUnavailable", False),
        (400, "AccessDeniedException", False),
        (400, "UnrecognizedClientException", False),
    ],
)
@pytest.mark.parametrize("in_header", [True, False])
def test_error_parsing_and_retry_classification(status: int, code: str, throttled: bool, in_header: bool) -> None:
    result = response({"__type": f"com.amazonaws.sagemaker#{code}"}, status, f"{code}:detail" if in_header else None)
    error = error_for_response(result)
    assert error.code == code
    assert isinstance(error, AwsSagemakerThrottledError) == throttled
    assert TRANSPORT_RETRY.is_retry("POST", status) == (status in {429, 503})


def test_body_throttle_retries_and_resigns(config: AwsSagemakerSourceConfig, transport: MagicMock) -> None:
    transport.post.side_effect = [response({"__type": "ThrottlingException"}, 400), response({"Models": []})]
    client = AwsSagemakerClient(config, "2017-07-24")
    request = cast(Any, client.request).retry_with(wait=wait_none())
    assert request(client, "ListModels", {"MaxResults": 1}) == {"Models": []}
    assert transport.post.call_count == 2


@pytest.mark.parametrize("schema_name,allowed", [(None, True), ("models", False)])
@pytest.mark.parametrize("code", ["AccessDenied", "AccessDeniedException"])
def test_missing_permission_is_accepted_only_at_creation(
    config: AwsSagemakerSourceConfig, transport: MagicMock, schema_name: str | None, allowed: bool, code: str
) -> None:
    transport.post.return_value = response({"__type": code}, 400)
    valid, message = validate_credentials(config, schema_name, "2017-07-24")
    assert valid is allowed
    if allowed:
        assert message is None
    else:
        assert message and "sagemaker:ListModels" in message and "sagemaker:DescribeModel" in message


@pytest.mark.parametrize("schema_name,requests_count", [(None, 1), ("models", 2)])
def test_validation_probes_describe_only_for_selected_table(
    config: AwsSagemakerSourceConfig, transport: MagicMock, schema_name: str | None, requests_count: int
) -> None:
    transport.post.side_effect = [
        response({"Models": [{"ModelName": "example"}]}),
        response({"ModelArn": "example-arn"}),
    ]
    assert validate_credentials(config, schema_name, "2017-07-24") == (True, None)
    assert transport.post.call_count == requests_count
    assert json.loads(transport.post.call_args_list[0].kwargs["data"]) == {"MaxResults": 1}


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("region", "us-east-1.example.com/", "Enter an AWS region"),
        ("aws_access_key_id", "", "Enter both"),
        ("aws_secret_access_key", "", "Enter both"),
    ],
)
def test_bad_config_never_sends_credentials(
    config: AwsSagemakerSourceConfig, transport: MagicMock, field: str, value: str, message: str
) -> None:
    setattr(config, field, value)
    valid, error = validate_credentials(config, None, "2017-07-24")
    assert valid is False and error and message in error
    transport.post.assert_not_called()


def test_unknown_table_and_version_are_rejected(config: AwsSagemakerSourceConfig, transport: MagicMock) -> None:
    assert validate_credentials(config, "unknown", "2017-07-24") == (False, "Unknown SageMaker table: unknown")
    assert validate_credentials(config, None, "invalid") == (False, "Unsupported SageMaker API version: invalid")
    with pytest.raises(UnknownResourceError):
        aws_sagemaker_source(config, "unknown", "2017-07-24", manager(), False, None)
    transport.post.assert_not_called()


def test_transient_validation_error_propagates(config: AwsSagemakerSourceConfig, transport: MagicMock) -> None:
    transport.post.return_value = response({"__type": "ServiceUnavailable"}, 503)
    with pytest.raises(AwsSagemakerError, match="ServiceUnavailable"):
        validate_credentials(config, "models", "2017-07-24")
    transport.close.assert_called_once()


def test_non_object_success_response_is_rejected(config: AwsSagemakerSourceConfig, transport: MagicMock) -> None:
    result = response({})
    result._content = b"[]"
    transport.post.return_value = result
    with pytest.raises(ValueError, match="invalid response"):
        AwsSagemakerClient(config, "2017-07-24").request("ListModels", {})


def test_non_json_error_does_not_leak_body(config: AwsSagemakerSourceConfig, transport: MagicMock) -> None:
    result = response({}, 502)
    result._content = b"upstream error with sensitive details"
    transport.post.return_value = result
    with pytest.raises(AwsSagemakerError, match="^AWS SageMaker request failed: HTTP 502$"):
        AwsSagemakerClient(config, "2017-07-24").request("ListModels", {})
