import json
from collections.abc import Generator, Iterable, Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from botocore.loaders import Loader

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_compute_optimizer import (
    aws_compute_optimizer as transport,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_compute_optimizer.aws_compute_optimizer import (
    AwsComputeOptimizerClient,
    AwsComputeOptimizerError,
    AwsComputeOptimizerResumeConfig,
    aws_compute_optimizer_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_compute_optimizer.source import (
    AwsComputeOptimizerSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awscomputeoptimizer import (
    AwsComputeOptimizerSourceConfig,
)


def config(region: str | None = "eu-west-1", token: str | None = None) -> AwsComputeOptimizerSourceConfig:
    return AwsComputeOptimizerSourceConfig(
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="fake-secret",
        aws_session_token=token,
        region=region,
    )


def response(payload: object, status: int = 200, headers: dict[str, str] | None = None) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    result.headers.update(headers or {})
    return result


@pytest.fixture
def session() -> Iterator[MagicMock]:
    with patch.object(transport, "make_tracked_session") as factory:
        yield factory.return_value


def manager(state: AwsComputeOptimizerResumeConfig | None = None) -> MagicMock:
    result = MagicMock()
    result.load_state.return_value = state
    return result


def driver(region: str | None = "eu-west-1", token: str | None = None) -> SourceDriver:
    return SourceDriver(AwsComputeOptimizerSource(), config(region, token))


@pytest.mark.parametrize(
    "region,token,host",
    [
        (None, None, "compute-optimizer.us-east-1.amazonaws.com"),
        ("eu-west-1", "fake-session-token", "compute-optimizer.eu-west-1.amazonaws.com"),
        ("cn-north-1", "fake-session-token", "compute-optimizer.cn-north-1.amazonaws.com.cn"),
        ("us-gov-west-1", None, "compute-optimizer.us-gov-west-1.amazonaws.com"),
    ],
)
def test_signed_json_request(region: str | None, token: str | None, host: str) -> None:
    model = Loader().load_service_model("compute-optimizer", "service-2", api_version="2019-11-01")
    with scripted_network(
        [
            ScriptedResponse(json={"status": "Active"}),
            ScriptedResponse(status=302, headers={"Location": "https://example.com/redirect"}),
        ]
    ) as network:
        client = AwsComputeOptimizerClient(config(region, token), "2019-11-01")
        assert client.request("GetEnrollmentStatus", {}) == {"status": "Active"}
        with pytest.raises(AwsComputeOptimizerError, match="HTTP 302"):
            client.request("GetEnrollmentStatus", {})
        client.close()

    assert len(network.requests_log) == 2
    request = network.requests_log[0]
    headers = request.headers
    assert request.url == f"https://{host}/"
    assert request.body == b"{}"
    assert headers["content-type"] == f"application/x-amz-json-{model['metadata']['jsonVersion']}"
    assert headers["x-amz-target"] == f"{model['metadata']['targetPrefix']}.GetEnrollmentStatus"
    assert f"/{region or 'us-east-1'}/compute-optimizer/aws4_request" in headers["authorization"]
    assert "x-amz-target" in headers["authorization"]
    assert headers.get("x-amz-security-token") == token
    assert "x-amz-date" in headers
    assert request.read_timeout == 60


@pytest.mark.parametrize(
    "endpoint,operation,key,item,primary_keys",
    [
        (
            "ec2_instance_recommendations",
            "GetEC2InstanceRecommendations",
            "instanceRecommendations",
            {"instanceArn": "arn:aws:ec2:eu-west-1:123456789012:instance/i-example"},
            ["instance_arn"],
        ),
        (
            "auto_scaling_group_recommendations",
            "GetAutoScalingGroupRecommendations",
            "autoScalingGroupRecommendations",
            {"autoScalingGroupArn": "arn:aws:autoscaling:eu-west-1:123456789012:autoScalingGroup:example"},
            ["auto_scaling_group_arn"],
        ),
        (
            "lambda_function_recommendations",
            "GetLambdaFunctionRecommendations",
            "lambdaFunctionRecommendations",
            {"functionArn": "arn:aws:lambda:eu-west-1:123456789012:function:example", "functionVersion": "$LATEST"},
            ["function_arn", "function_version"],
        ),
        (
            "ecs_service_recommendations",
            "GetECSServiceRecommendations",
            "ecsServiceRecommendations",
            {"serviceArn": "arn:aws:ecs:eu-west-1:123456789012:service/example/service"},
            ["service_arn"],
        ),
        (
            "ebs_volume_recommendations",
            "GetEBSVolumeRecommendations",
            "volumeRecommendations",
            {"volumeArn": "arn:aws:ec2:eu-west-1:123456789012:volume/vol-example"},
            ["volume_arn"],
        ),
        (
            "rds_database_recommendations",
            "GetRDSDatabaseRecommendations",
            "rdsDBRecommendations",
            {"resourceArn": "arn:aws:rds:eu-west-1:123456789012:db:example"},
            ["resource_arn"],
        ),
        (
            "idle_recommendations",
            "GetIdleRecommendations",
            "idleRecommendations",
            {"resourceArn": "arn:aws:ec2:eu-west-1:123456789012:volume/vol-idle", "resourceType": "EBSVolume"},
            ["resource_arn"],
        ),
        (
            "recommendation_summaries",
            "GetRecommendationSummaries",
            "recommendationSummaries",
            {"accountId": "123456789012", "recommendationResourceType": "Ec2Instance"},
            ["account_id", "recommendation_resource_type", "region"],
        ),
    ],
)
def test_full_refresh_pagination(
    session: MagicMock, endpoint: str, operation: str, key: str, item: dict[str, Any], primary_keys: list[str]
) -> None:
    session.post.side_effect = [
        response({key: [item], "nextToken": "page-2"}),
        response({key: [], "nextToken": "page-3"}),
        response({key: [item], "nextToken": None}),
    ]
    resume = manager()
    source = aws_compute_optimizer_source(config(), endpoint, resume)
    rows = list(cast(Iterable[Any], source.items()))
    assert len(rows) == 2
    assert all(rows[0][0][column] for column in primary_keys)
    assert source.primary_keys == primary_keys
    assert rows[0][0]["region"] == "eu-west-1"
    assert source.sort_mode is None
    assert source.partition_keys is None
    calls = session.post.call_args_list
    assert [json.loads(call.kwargs["data"]) for call in calls] == [
        {"maxResults": 100},
        {"maxResults": 100, "nextToken": "page-2"},
        {"maxResults": 100, "nextToken": "page-3"},
    ]
    assert all(call.kwargs["headers"]["X-Amz-Target"] == f"ComputeOptimizerService.{operation}" for call in calls)
    assert [call.args[0] for call in resume.save_state.call_args_list] == [
        AwsComputeOptimizerResumeConfig(next_token="page-2"),
        AwsComputeOptimizerResumeConfig(next_token="page-3"),
        AwsComputeOptimizerResumeConfig(complete=True),
    ]
    assert resume.safe_point.call_count == 3
    resume.clear_state.assert_not_called()
    assert source.on_complete is not None
    source.on_complete()
    resume.clear_state.assert_called_once()
    session.close.assert_called_once()


EC2_ARN = "arn:aws:ec2:eu-west-1:123456789012:instance/i-example"
ECS_ARN = "arn:aws:ecs:eu-west-1:123456789012:service/example/service"


@pytest.mark.parametrize(
    "endpoint,parent_operation,parent_key,arn_field,lookback_field,option,metric,expected",
    [
        (
            "ec2_recommendation_projected_metrics",
            "GetEC2InstanceRecommendations",
            "instanceRecommendations",
            "instanceArn",
            "lookBackPeriodInDays",
            {"recommendedInstanceType": "m7i.large", "rank": 1},
            {"name": "Cpu", "timestamps": [1735689600, 1735776000], "values": [40.5, 12.0]},
            [
                {"instance_arn": EC2_ARN, "recommended_instance_type": "m7i.large", "rank": 1, "value": 40.5},
                {"instance_arn": EC2_ARN, "recommended_instance_type": "m7i.large", "rank": 1, "value": 12.0},
            ],
        ),
        (
            "ecs_service_recommendation_projected_metrics",
            "GetECSServiceRecommendations",
            "ecsServiceRecommendations",
            "serviceArn",
            "lookbackPeriodInDays",
            {"recommendedCpuUnits": 256, "recommendedMemorySize": 512},
            {
                "name": "Memory",
                "timestamps": [1735689600, 1735776000],
                "upperBoundValues": [70.0, 60.0],
                "lowerBoundValues": [30.0],
            },
            [
                {
                    "service_arn": ECS_ARN,
                    "recommended_cpu_units": 256,
                    "recommended_memory_size": 512,
                    "upper_bound_value": 70.0,
                    "lower_bound_value": 30.0,
                },
                {
                    "service_arn": ECS_ARN,
                    "recommended_cpu_units": 256,
                    "recommended_memory_size": 512,
                    "upper_bound_value": 60.0,
                    "lower_bound_value": None,
                },
            ],
        ),
    ],
)
def test_projected_metrics_fan_out_over_recommendations(
    endpoint: str,
    parent_operation: str,
    parent_key: str,
    arn_field: str,
    lookback_field: str,
    option: dict[str, Any],
    metric: dict[str, Any],
    expected: list[dict[str, Any]],
) -> None:
    arn = expected[0][transport._column(arn_field)]
    result = driver().run(
        endpoint,
        [
            ScriptedResponse(
                json={parent_key: [{arn_field: "arn:gone"}, {arn_field: arn, lookback_field: 32}], "nextToken": "p2"}
            ),
            ScriptedResponse(status=400, json={"__type": "ResourceNotFoundException"}),
            ScriptedResponse(json={"recommendedOptionProjectedMetrics": [{**option, "projectedMetrics": [metric]}]}),
            ScriptedResponse(json={parent_key: [], "nextToken": None}),
        ],
    )
    assert result.raised is None
    timestamps = [datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)]
    assert result.rows == [
        {**row, "metric_name": metric["name"], "timestamp": timestamp, "region": "eu-west-1"}
        for row, timestamp in zip(expected, timestamps)
    ]
    bodies = [json.loads(request.body or b"{}") for request in result.requests]
    targets = [request.headers["x-amz-target"].rsplit(".", 1)[-1] for request in result.requests]
    assert targets[0] == targets[3] == parent_operation
    assert bodies[0] == {"maxResults": 100}
    assert bodies[3] == {"maxResults": 100, "nextToken": "p2"}
    gone, child = bodies[1], bodies[2]
    assert gone[arn_field] == "arn:gone"
    assert gone["endTime"] - gone["startTime"] == 14 * 86400
    assert child == {
        arn_field: arn,
        "stat": "Maximum",
        "period": 86400,
        "startTime": child["endTime"] - 32 * 86400,
        "endTime": child["endTime"],
    }
    assert child["endTime"] % 86400 == 0
    assert [
        (state.next_token, [tuple(parent) for parent in state.pending], state.complete)
        for state in result.committed_states
    ] == [("p2", [(arn, 32)], False), ("p2", [], False), (None, [], True)]
    assert result.completed_state is None


def test_projected_metrics_resume_processes_pending_parents_without_refetching_page() -> None:
    result = driver().run(
        "ec2_recommendation_projected_metrics",
        [ScriptedResponse(json={"recommendedOptionProjectedMetrics": []})],
        resume_state=AwsComputeOptimizerResumeConfig(pending=((EC2_ARN, 14),)),
    )
    assert result.raised is None
    assert [json.loads(request.body or b"{}").get("instanceArn") for request in result.requests] == [EC2_ARN]
    assert (result.final_state.next_token, list(result.final_state.pending), result.final_state.complete) == (
        None,
        [],
        True,
    )


def test_completed_resume_does_not_refetch() -> None:
    result = driver().run(
        "ec2_instance_recommendations", [], resume_state=AwsComputeOptimizerResumeConfig(complete=True)
    )
    assert result.raised is None
    assert result.rows == []
    assert result.requests == []


def test_resume_is_staged_before_batch_and_not_cleared_early(session: MagicMock) -> None:
    session.post.return_value = response({"instanceRecommendations": [{"instanceArn": "example"}], "nextToken": "next"})
    resume = manager()
    source = aws_compute_optimizer_source(config(), "ec2_instance_recommendations", resume)
    iterator = cast(Generator[list[dict[str, Any]]], source.items())
    assert next(iterator) == [{"instance_arn": "example", "region": "eu-west-1"}]
    resume.save_state.assert_called_once_with(AwsComputeOptimizerResumeConfig(next_token="next"))
    resume.clear_state.assert_not_called()
    iterator.close()
    session.close.assert_called_once()


def test_repeated_token_fails_without_marking_complete(session: MagicMock) -> None:
    session.post.return_value = response({"nextToken": "same"})
    resume = manager(AwsComputeOptimizerResumeConfig(next_token="same"))
    source = aws_compute_optimizer_source(config(), "ec2_instance_recommendations", resume)
    with pytest.raises(ValueError, match="repeated a pagination token"):
        list(cast(Iterable[Any], source.items()))
    resume.save_state.assert_not_called()
    session.close.assert_called_once()


def test_normalization_preserves_options_and_converts_timestamp() -> None:
    options = [{"instanceType": "m7i.large", "rank": 1}]
    row = transport.normalize_row(
        {
            "lastRefreshTimestamp": 1735689600,
            "recommendationOptions": options,
            "savingsOpportunity": {"estimatedMonthlySavings": {"value": 12.5, "currency": "USD"}},
        },
        "eu-west-1",
    )
    assert row == {
        "last_refresh_timestamp": datetime(2025, 1, 1, tzinfo=UTC),
        "recommendation_options": options,
        "savings_opportunity_estimated_monthly_savings_value": 12.5,
        "savings_opportunity_estimated_monthly_savings_currency": "USD",
        "region": "eu-west-1",
    }


@pytest.mark.parametrize(
    "code,status,attempts",
    [
        ("ThrottlingException", 400, 4),
        ("AccessDeniedException", 400, 1),
        ("InternalServerException", 500, 1),
        ("ThrottlingException", 429, 1),
    ],
)
def test_only_body_throttling_has_application_retries(code: str, status: int, attempts: int) -> None:
    answer = ScriptedResponse(status=status, json={"__type": f"com.amazonaws.computeoptimizer#{code}"})
    with scripted_network(always(answer)) as network:
        client = AwsComputeOptimizerClient(config())
        with pytest.raises(AwsComputeOptimizerError) as raised:
            client.request("GetEnrollmentStatus", {})
        client.close()
    assert raised.value.code == code
    transport_attempts = 4 if status in (429, 500) else 1
    assert len(network.requests_log) == attempts * transport_attempts


@pytest.mark.parametrize(
    "payload,status,headers,code",
    [
        ({"__type": "namespace#OptInRequiredException"}, 400, {}, "OptInRequiredException"),
        ({"code": "InvalidClientTokenId"}, 403, {}, "InvalidClientTokenId"),
        ({}, 403, {"x-amzn-ErrorType": "AccessDeniedException:extra"}, "AccessDeniedException"),
        ("unavailable", 503, {}, "HTTP 503"),
        ([], 502, {}, "HTTP 502"),
    ],
)
def test_error_parsing(payload: object, status: int, headers: dict[str, str], code: str) -> None:
    assert transport.error_for_response(response(payload, status, headers)).code == code


def test_partial_error_does_not_commit_incomplete_data(session: MagicMock) -> None:
    session.post.return_value = response(
        {
            "instanceRecommendations": [{"instanceArn": "example"}],
            "errors": [{"code": "AccessDeniedException", "message": "denied"}],
        }
    )
    resume = manager()
    source = aws_compute_optimizer_source(config(), "ec2_instance_recommendations", resume)
    with pytest.raises(AwsComputeOptimizerError, match="AccessDeniedException"):
        list(cast(Iterable[Any], source.items()))
    resume.save_state.assert_not_called()
    session.close.assert_called_once()


@pytest.mark.parametrize("schema,valid", [(None, True), ("ec2_instance_recommendations", False)])
def test_missing_permission_at_creation_and_per_table(session: MagicMock, schema: str | None, valid: bool) -> None:
    session.post.return_value = response({"__type": "AccessDeniedException"}, 400)
    result, message = validate_credentials(config(), schema)
    assert result is valid
    if schema is None:
        assert message is None
        assert session.post.call_args.kwargs["headers"]["X-Amz-Target"].endswith(".GetEnrollmentStatus")
        assert json.loads(session.post.call_args.kwargs["data"]) == {}
    else:
        assert message and "compute-optimizer:GetEC2InstanceRecommendations" in message
        assert json.loads(session.post.call_args.kwargs["data"]) == {"maxResults": 1}
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "listing,metrics,valid,targets",
    [
        (
            [{"instanceArn": EC2_ARN}],
            ScriptedResponse(status=400, json={"__type": "AccessDeniedException"}),
            False,
            ["GetEC2InstanceRecommendations", "GetEC2RecommendationProjectedMetrics"],
        ),
        (
            [{"instanceArn": EC2_ARN}],
            ScriptedResponse(json={"recommendedOptionProjectedMetrics": []}),
            True,
            ["GetEC2InstanceRecommendations", "GetEC2RecommendationProjectedMetrics"],
        ),
        ([], None, True, ["GetEC2InstanceRecommendations"]),
    ],
)
def test_projected_metrics_validation_probes_metrics_permission(
    listing: list[dict[str, Any]], metrics: ScriptedResponse | None, valid: bool, targets: list[str]
) -> None:
    script = [ScriptedResponse(json={"instanceRecommendations": listing}), *([metrics] if metrics else [])]
    with scripted_network(script) as network:
        result, message = validate_credentials(config(), "ec2_recommendation_projected_metrics")
    assert result is valid
    assert (message is None) is valid
    if not valid:
        assert message and "compute-optimizer:GetEC2RecommendationProjectedMetrics" in message
    assert [request.headers["x-amz-target"].rsplit(".", 1)[-1] for request in network.requests_log] == targets


@pytest.mark.parametrize("status,valid", [("Active", True), ("Inactive", False), ("Pending", False), ("Failed", False)])
def test_enrollment_validation(status: str, valid: bool) -> None:
    with scripted_network([ScriptedResponse(json={"status": status})]) as network:
        result, message = validate_credentials(config())
    assert result is valid
    assert (message is None) is valid
    assert len(network.requests_log) == 1


@pytest.mark.parametrize(
    "code,expected",
    [
        ("UnrecognizedClientException", "credentials"),
        ("InvalidSignatureException", "signature"),
        ("SignatureDoesNotMatch", "signature"),
        ("ExpiredTokenException", "expired"),
        ("OptInRequiredException", "Enable AWS Compute Optimizer"),
        ("SubscriptionRequiredException", "Enable AWS Compute Optimizer"),
    ],
)
def test_credentials_and_sync_errors_are_actionable(code: str, expected: str) -> None:
    with scripted_network([ScriptedResponse(status=400, json={"__type": code})]) as network:
        valid, message = validate_credentials(config())
    assert not valid
    assert message and expected in message
    assert len(network.requests_log) == 1
    mappings = AwsComputeOptimizerSource().get_non_retryable_errors()
    assert mappings[str(AwsComputeOptimizerError(code))] == message


@pytest.mark.parametrize("error", [requests.Timeout(), ValueError("invalid JSON")])
def test_validation_network_or_response_failure(session: MagicMock, error: Exception) -> None:
    session.post.side_effect = error
    assert validate_credentials(config()) == (False, "Could not reach the AWS Compute Optimizer API. Try again.")
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "region", ["https://example.com", "us-east-1.example.com", "us-east-1/", "us-east-1@evil", " us-east-1"]
)
def test_rejects_invalid_region_before_request(region: str) -> None:
    with scripted_network([]) as network:
        assert validate_credentials(config(region)) == (False, "Enter an AWS region, such as us-east-1.")
    assert network.requests_log == []


def test_unknown_schema_and_version_rejected() -> None:
    with scripted_network([]) as network:
        assert validate_credentials(config(), "unknown")[0] is False
        assert validate_credentials(config(), api_version="2000-01-01")[0] is False
    result = driver().run("unknown", [])
    assert isinstance(result.raised, ValueError)
    assert "Unknown AWS Compute Optimizer table" in str(result.raised)
    assert network.requests_log == []
    assert result.requests == []
