import json
import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests

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
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_sagemaker.source import AwsSagemakerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
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


def driver(config: AwsSagemakerSourceConfig) -> SourceDriver:
    return SourceDriver(AwsSagemakerSource(), config)


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
    config: AwsSagemakerSourceConfig, region: str, host: str, session_token: str | None
) -> None:
    config.region = region
    config.aws_session_token = session_token
    with scripted_network([ScriptedResponse(json={"Models": []})]) as network:
        client = AwsSagemakerClient(config, "2017-07-24")
        try:
            assert client.request("ListModels", {"MaxResults": 1}) == {"Models": []}
        finally:
            client.close()
    assert len(network.requests_log) == 1
    sent = network.requests_log[0]
    assert sent.url == f"https://{host}/"
    assert sent.json() == {"MaxResults": 1}
    assert sent.headers["content-type"] == "application/x-amz-json-1.1"
    assert sent.headers["x-amz-target"] == "SageMaker.ListModels"
    assert "AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/" in sent.headers["authorization"]
    assert f"/{region}/sagemaker/aws4_request" in sent.headers["authorization"]
    assert sent.headers.get("x-amz-security-token") == session_token
    assert sent.headers["x-amz-date"]
    assert sent.read_timeout == 60

    with scripted_network([ScriptedResponse(status=302, headers={"Location": "https://example.com/"})]) as network:
        client = AwsSagemakerClient(config, "2017-07-24")
        try:
            with pytest.raises(AwsSagemakerError):
                client.request("ListModels", {"MaxResults": 1})
        finally:
            client.close()
    assert len(network.requests_log) == 1


@pytest.mark.parametrize(
    "endpoint,list_operation,result_key,describe_operation,name_field,arn_field,column,list_filters,describe_payload",
    [
        (
            "training_jobs",
            "ListTrainingJobs",
            "TrainingJobSummaries",
            "DescribeTrainingJob",
            "TrainingJobName",
            "TrainingJobArn",
            "training_job_arn",
            {},
            {"TrainingJobName": "example"},
        ),
        (
            "processing_jobs",
            "ListProcessingJobs",
            "ProcessingJobSummaries",
            "DescribeProcessingJob",
            "ProcessingJobName",
            "ProcessingJobArn",
            "processing_job_arn",
            {},
            {"ProcessingJobName": "example"},
        ),
        (
            "endpoints",
            "ListEndpoints",
            "Endpoints",
            "DescribeEndpoint",
            "EndpointName",
            "EndpointArn",
            "endpoint_arn",
            {},
            {"EndpointName": "example"},
        ),
        (
            "models",
            "ListModels",
            "Models",
            "DescribeModel",
            "ModelName",
            "ModelArn",
            "model_arn",
            {},
            {"ModelName": "example"},
        ),
        (
            "endpoint_configs",
            "ListEndpointConfigs",
            "EndpointConfigs",
            "DescribeEndpointConfig",
            "EndpointConfigName",
            "EndpointConfigArn",
            "endpoint_config_arn",
            {},
            {"EndpointConfigName": "example"},
        ),
        (
            "model_packages",
            "ListModelPackages",
            "ModelPackageSummaryList",
            "DescribeModelPackage",
            "ModelPackageName",
            "ModelPackageArn",
            "model_package_arn",
            {"ModelPackageType": "Both"},
            {"ModelPackageName": "arn-of-example"},
        ),
        (
            "hyperparameter_tuning_jobs",
            "ListHyperParameterTuningJobs",
            "HyperParameterTuningJobSummaries",
            "DescribeHyperParameterTuningJob",
            "HyperParameterTuningJobName",
            "HyperParameterTuningJobArn",
            "hyper_parameter_tuning_job_arn",
            {},
            {"HyperParameterTuningJobName": "example"},
        ),
        (
            "automl_jobs",
            "ListAutoMLJobs",
            "AutoMLJobSummaries",
            "DescribeAutoMLJobV2",
            "AutoMLJobName",
            "AutoMLJobArn",
            "auto_ml_job_arn",
            {},
            {"AutoMLJobName": "example"},
        ),
        (
            "transform_jobs",
            "ListTransformJobs",
            "TransformJobSummaries",
            "DescribeTransformJob",
            "TransformJobName",
            "TransformJobArn",
            "transform_job_arn",
            {},
            {"TransformJobName": "example"},
        ),
        (
            "experiments",
            "ListExperiments",
            "ExperimentSummaries",
            "DescribeExperiment",
            "ExperimentName",
            "ExperimentArn",
            "experiment_arn",
            {},
            {"ExperimentName": "example"},
        ),
        (
            "trials",
            "ListTrials",
            "TrialSummaries",
            "DescribeTrial",
            "TrialName",
            "TrialArn",
            "trial_arn",
            {},
            {"TrialName": "example"},
        ),
        (
            "trial_components",
            "ListTrialComponents",
            "TrialComponentSummaries",
            "DescribeTrialComponent",
            "TrialComponentName",
            "TrialComponentArn",
            "trial_component_arn",
            {},
            {"TrialComponentName": "example"},
        ),
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
    list_filters: dict[str, str],
    describe_payload: dict[str, str],
) -> None:
    transport.post.side_effect = [
        response({result_key: [{name_field: "example", arn_field: "arn-of-example"}], "NextToken": "second"}),
        response(
            {
                arn_field: "arn:aws:sagemaker:eu-west-1:123456789012:example/item",
                "CreationTime": 1704067200,
                "ResourceConfig": {"InstanceCount": 2},
            }
        ),
        response({result_key: [], "NextToken": "last"}),
        response({result_key: [{name_field: "other", arn_field: "arn-of-other"}]}),
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
        **list_filters,
    }
    assert json.loads(calls[1].kwargs["data"]) == describe_payload
    assert json.loads(calls[2].kwargs["data"])["NextToken"] == "second"
    assert json.loads(calls[3].kwargs["data"])["NextToken"] == "last"
    assert [call.args[0] for call in resume.save_state.call_args_list] == [
        AwsSagemakerResumeConfig(next_token="second"),
        AwsSagemakerResumeConfig(next_token="last"),
        AwsSagemakerResumeConfig(complete=True),
    ]
    assert resume.safe_point.call_count == 3
    transport.close.assert_called_once()


def execution(arn: str) -> ScriptedResponse:
    return ScriptedResponse(json={"PipelineExecutionArn": arn, "CreationTime": 1704067200})


@pytest.mark.parametrize(
    "resume_state,script,expected_targets,expected_rows,expected_states",
    [
        (
            None,
            [
                ScriptedResponse(json={"PipelineSummaries": [{"PipelineName": "zeta"}], "NextToken": "p2"}),
                ScriptedResponse(json={"PipelineSummaries": [{"PipelineName": "alpha"}]}),
                ScriptedResponse(
                    json={"PipelineExecutionSummaries": [{"PipelineExecutionArn": "arn-a1"}], "NextToken": "a2"}
                ),
                execution("arn-a1"),
                ScriptedResponse(json={"PipelineExecutionSummaries": []}),
                ScriptedResponse(json={"PipelineExecutionSummaries": [{"PipelineExecutionArn": "arn-z1"}]}),
                execution("arn-z1"),
            ],
            [
                ("ListPipelines", {"MaxResults": 100, "SortBy": "Name", "SortOrder": "Ascending"}),
                ("ListPipelines", {"NextToken": "p2"}),
                ("ListPipelineExecutions", {"PipelineName": "alpha"}),
                ("DescribePipelineExecution", {"PipelineExecutionArn": "arn-a1"}),
                ("ListPipelineExecutions", {"PipelineName": "alpha", "NextToken": "a2"}),
                ("ListPipelineExecutions", {"PipelineName": "zeta"}),
                ("DescribePipelineExecution", {"PipelineExecutionArn": "arn-z1"}),
            ],
            ["arn-a1", "arn-z1"],
            [
                AwsSagemakerResumeConfig(next_token="a2", parent_name="alpha"),
                AwsSagemakerResumeConfig(parent_name="zeta"),
                AwsSagemakerResumeConfig(complete=True),
            ],
        ),
        (
            AwsSagemakerResumeConfig(next_token="m2", parent_name="middle"),
            [
                ScriptedResponse(
                    json={"PipelineSummaries": [{"PipelineName": "zeta"}, {"PipelineName": "alpha"}]},
                ),
                ScriptedResponse(json={"PipelineExecutionSummaries": [{"PipelineExecutionArn": "arn-z1"}]}),
                execution("arn-z1"),
            ],
            [
                ("ListPipelines", {}),
                ("ListPipelineExecutions", {"PipelineName": "zeta"}),
                ("DescribePipelineExecution", {"PipelineExecutionArn": "arn-z1"}),
            ],
            ["arn-z1"],
            [AwsSagemakerResumeConfig(complete=True)],
        ),
        (
            None,
            [
                ScriptedResponse(json={"PipelineSummaries": [{"PipelineName": "zeta"}, {"PipelineName": "alpha"}]}),
                ScriptedResponse(status=400, json={"__type": "ResourceNotFound"}),
                ScriptedResponse(json={"PipelineExecutionSummaries": [{"PipelineExecutionArn": "arn-z1"}]}),
                execution("arn-z1"),
            ],
            [
                ("ListPipelines", {}),
                ("ListPipelineExecutions", {"PipelineName": "alpha"}),
                ("ListPipelineExecutions", {"PipelineName": "zeta"}),
                ("DescribePipelineExecution", {"PipelineExecutionArn": "arn-z1"}),
            ],
            ["arn-z1"],
            [AwsSagemakerResumeConfig(parent_name="zeta"), AwsSagemakerResumeConfig(complete=True)],
        ),
    ],
)
def test_pipeline_executions_walk_every_pipeline_and_resume_from_the_saved_one(
    config: AwsSagemakerSourceConfig,
    resume_state: AwsSagemakerResumeConfig | None,
    script: list[ScriptedResponse],
    expected_targets: list[tuple[str, dict[str, object]]],
    expected_rows: list[str],
    expected_states: list[AwsSagemakerResumeConfig],
) -> None:
    result = driver(config).run("pipeline_executions", script, resume_state=resume_state)
    assert result.raised is None
    assert [row["pipeline_execution_arn"] for row in result.rows] == expected_rows
    assert len(result.requests) == len(expected_targets)
    for sent, (operation, payload) in zip(result.requests, expected_targets):
        assert sent.headers["x-amz-target"] == f"SageMaker.{operation}"
        assert payload.items() <= sent.json().items()
    assert result.saved_states == expected_states


def test_monitoring_executions_use_list_summaries_as_rows(config: AwsSagemakerSourceConfig) -> None:
    summary = {
        "MonitoringScheduleName": "schedule",
        "ScheduledTime": 1704067200,
        "CreationTime": 1704067260,
        "LastModifiedTime": 1704067320,
        "MonitoringExecutionStatus": "Failed",
        "FailureReason": "Baseline missing",
    }
    result = driver(config).run(
        "monitoring_executions",
        [ScriptedResponse(json={"MonitoringExecutionSummaries": [summary, {**summary, "ScheduledTime": None}]})],
    )
    assert isinstance(result.raised, ValueError)
    assert result.saved_states == []

    result = driver(config).run(
        "monitoring_executions", [ScriptedResponse(json={"MonitoringExecutionSummaries": [summary]})]
    )
    assert result.raised is None
    assert len(result.requests) == 1
    assert result.requests[0].headers["x-amz-target"] == "SageMaker.ListMonitoringExecutions"
    assert result.rows == [
        {
            "monitoring_schedule_name": "schedule",
            "scheduled_time": dt.datetime(2024, 1, 1, tzinfo=dt.UTC),
            "creation_time": dt.datetime(2024, 1, 1, 0, 1, tzinfo=dt.UTC),
            "last_modified_time": dt.datetime(2024, 1, 1, 0, 2, tzinfo=dt.UTC),
            "monitoring_execution_status": "Failed",
            "failure_reason": "Baseline missing",
        }
    ]
    assert result.response and result.response.primary_keys == ["monitoring_schedule_name", "scheduled_time"]


@pytest.mark.parametrize("incremental", [True, False])
@pytest.mark.parametrize(
    "last_value",
    [1704067200, 1704067200.0, "2024-01-01T00:00:00Z", dt.datetime(2024, 1, 1), dt.datetime(2024, 1, 1, tzinfo=dt.UTC)],
)
def test_incremental_filter_and_full_refresh(
    config: AwsSagemakerSourceConfig,
    incremental: bool,
    last_value: dt.datetime | str | int | float | None,
) -> None:
    result = driver(config).run(
        "models",
        [ScriptedResponse(json={"Models": [], "NextToken": "next"}), ScriptedResponse(json={"Models": []})],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=last_value,
    )
    assert result.raised is None
    assert result.rows == []
    assert result.response and result.response.sort_mode == "asc"
    for sent in result.requests:
        payload = sent.json()
        assert payload.get("CreationTimeAfter") == (1704067200.0 if incremental else None)
        assert payload["SortOrder"] == "Ascending"


def test_resume_preserves_original_filter(config: AwsSagemakerSourceConfig) -> None:
    result = driver(config).run(
        "models",
        [ScriptedResponse(json={"Models": []})],
        resume_state=AwsSagemakerResumeConfig(next_token="resume", watermark=1704067200.0),
        should_use_incremental_field=True,
        db_incremental_field_last_value=1705000000,
    )
    assert result.raised is None
    assert result.rows == []
    payload = result.requests[0].json()
    assert payload["NextToken"] == "resume"
    assert payload["CreationTimeAfter"] == 1704067200.0


def test_complete_resume_makes_no_request(config: AwsSagemakerSourceConfig) -> None:
    result = driver(config).run(
        "models", [], resume_state=AwsSagemakerResumeConfig(complete=True), should_use_incremental_field=True
    )
    assert result.raised is None
    assert result.rows == []
    assert result.requests == []


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


def test_body_throttle_retries_and_resigns(config: AwsSagemakerSourceConfig) -> None:
    with scripted_network(
        [ScriptedResponse(status=400, json={"__type": "ThrottlingException"}), ScriptedResponse(json={"Models": []})]
    ) as network:
        client = AwsSagemakerClient(config, "2017-07-24")
        try:
            assert client.request("ListModels", {"MaxResults": 1}) == {"Models": []}
        finally:
            client.close()
    assert len(network.requests_log) == 2
    assert all(sent.headers["authorization"].startswith("AWS4-HMAC-SHA256 ") for sent in network.requests_log)


@pytest.mark.parametrize("schema_name,allowed", [(None, True), ("models", False)])
@pytest.mark.parametrize("code", ["AccessDenied", "AccessDeniedException"])
def test_missing_permission_is_accepted_only_at_creation(
    config: AwsSagemakerSourceConfig, schema_name: str | None, allowed: bool, code: str
) -> None:
    with scripted_network([ScriptedResponse(status=400, json={"__type": code})]) as network:
        valid, message = validate_credentials(config, schema_name, "2017-07-24")
    assert valid is allowed
    assert len(network.requests_log) == 1
    if allowed:
        assert message is None
    else:
        assert message and "sagemaker:ListModels" in message and "sagemaker:DescribeModel" in message


@pytest.mark.parametrize("schema_name,requests_count", [(None, 1), ("models", 2)])
def test_validation_probes_describe_only_for_selected_table(
    config: AwsSagemakerSourceConfig, schema_name: str | None, requests_count: int
) -> None:
    with scripted_network(
        [
            ScriptedResponse(json={"Models": [{"ModelName": "example"}]}),
            ScriptedResponse(json={"ModelArn": "example-arn"}),
        ]
    ) as network:
        assert validate_credentials(config, schema_name, "2017-07-24") == (True, None)
    assert len(network.requests_log) == requests_count
    assert network.requests_log[0].json() == {"MaxResults": 1}
    if schema_name:
        assert network.requests_log[1].json() == {"ModelName": "example"}


@pytest.mark.parametrize(
    "schema_name,script,expected_targets",
    [
        (
            "pipeline_executions",
            [
                ScriptedResponse(json={"PipelineSummaries": [{"PipelineName": "pipeline"}]}),
                ScriptedResponse(json={"PipelineExecutionSummaries": [{"PipelineExecutionArn": "arn-1"}]}),
                ScriptedResponse(json={"PipelineExecutionArn": "arn-1"}),
            ],
            [
                ("ListPipelines", {"MaxResults": 1}),
                ("ListPipelineExecutions", {"MaxResults": 1, "PipelineName": "pipeline"}),
                ("DescribePipelineExecution", {"PipelineExecutionArn": "arn-1"}),
            ],
        ),
        (
            "pipeline_executions",
            [ScriptedResponse(json={"PipelineSummaries": []})],
            [("ListPipelines", {"MaxResults": 1})],
        ),
        (
            "monitoring_executions",
            [ScriptedResponse(json={"MonitoringExecutionSummaries": [{"MonitoringScheduleName": "schedule"}]})],
            [("ListMonitoringExecutions", {"MaxResults": 1})],
        ),
    ],
)
def test_validation_probes_parent_and_skips_missing_describe(
    config: AwsSagemakerSourceConfig,
    schema_name: str,
    script: list[ScriptedResponse],
    expected_targets: list[tuple[str, dict[str, object]]],
) -> None:
    with scripted_network(script) as network:
        assert validate_credentials(config, schema_name, "2017-07-24") == (True, None)
    assert [(sent.headers["x-amz-target"], sent.json()) for sent in network.requests_log] == [
        (f"SageMaker.{operation}", payload) for operation, payload in expected_targets
    ]


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("region", "us-east-1.example.com/", "Enter an AWS region"),
        ("aws_access_key_id", "", "Enter both"),
        ("aws_secret_access_key", "", "Enter both"),
    ],
)
def test_bad_config_never_sends_credentials(
    config: AwsSagemakerSourceConfig, field: str, value: str, message: str
) -> None:
    setattr(config, field, value)
    with scripted_network([]) as network:
        valid, error = validate_credentials(config, None, "2017-07-24")
    assert valid is False and error and message in error
    assert network.requests_log == []


def test_unknown_table_and_version_are_rejected(config: AwsSagemakerSourceConfig) -> None:
    with scripted_network([]) as network:
        assert validate_credentials(config, "unknown", "2017-07-24") == (False, "Unknown SageMaker table: unknown")
        assert validate_credentials(config, None, "invalid") == (False, "Unsupported SageMaker API version: invalid")
    result = driver(config).run("unknown", [])
    assert isinstance(result.raised, UnknownResourceError)
    assert network.requests_log == []
    assert result.requests == []


def test_transient_validation_error_reports_an_unreachable_vendor(
    config: AwsSagemakerSourceConfig, transport: MagicMock
) -> None:
    transport.post.return_value = response({"__type": "ServiceUnavailable"}, 503)
    assert validate_credentials(config, "models", "2017-07-24") == (
        False,
        "Couldn't reach AWS SageMaker to check your credentials. Try again in a few minutes.",
    )
    transport.close.assert_called_once()


def test_non_object_success_response_is_rejected(config: AwsSagemakerSourceConfig) -> None:
    with scripted_network([ScriptedResponse(json=[])]) as network:
        client = AwsSagemakerClient(config, "2017-07-24")
        try:
            with pytest.raises(ValueError, match="invalid response"):
                client.request("ListModels", {})
        finally:
            client.close()
    assert len(network.requests_log) == 1


def test_non_json_error_does_not_leak_body(config: AwsSagemakerSourceConfig) -> None:
    with scripted_network(
        always(ScriptedResponse(status=502, body=b"upstream error with sensitive details"))
    ) as network:
        client = AwsSagemakerClient(config, "2017-07-24")
        try:
            with pytest.raises(AwsSagemakerError, match="^AWS SageMaker request failed: HTTP 502$"):
                client.request("ListModels", {})
        finally:
            client.close()
    assert len(network.requests_log) > 1
