import json
import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_config import aws_config
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_config.aws_config import (
    AwsConfigClient,
    AwsConfigError,
    AwsConfigResumeConfig,
    AwsConfigThrottledError,
    aws_config_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_config.source import AwsConfigSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsconfig import (
    AwsConfigSourceConfig,
)


def make_config(**overrides: Any) -> AwsConfigSourceConfig:
    return AwsConfigSourceConfig.from_dict(
        {
            "aws_access_key_id": "AKIAEXAMPLE",
            "aws_secret_access_key": "example-secret",
            "aws_session_token": "example-session",
            "region": "eu-west-1",
            **overrides,
        }
    )


def make_response(body: Any, status: int = 200, headers: dict[str, str] | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    response.headers.update(headers or {})
    return response


@pytest.fixture
def session() -> Iterator[MagicMock]:
    with patch.object(aws_config, "make_tracked_session") as factory:
        factory.return_value.post.return_value = make_response({})
        yield factory.return_value


def make_manager(state: AwsConfigResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = state is not None
    manager.load_state.return_value = state
    return manager


@pytest.mark.parametrize(
    "region,token,host,signing_region",
    [
        ("eu-west-1", "example-session", "config.eu-west-1.amazonaws.com", "eu-west-1"),
        ("cn-north-1", None, "config.cn-north-1.amazonaws.com.cn", "cn-north-1"),
        ("us-gov-west-1", None, "config.us-gov-west-1.amazonaws.com", "us-gov-west-1"),
        (None, None, "config.us-east-1.amazonaws.com", "us-east-1"),
    ],
)
def test_signed_tracked_request(region: str | None, token: str | None, host: str, signing_region: str) -> None:
    with scripted_network([ScriptedResponse(json={"ConfigRules": []})]) as network:
        client = AwsConfigClient(make_config(region=region, aws_session_token=token), "2014-11-12")
        assert client.request("DescribeConfigRules", {"NextToken": "page-2"}) == {"ConfigRules": []}
        client.close()

    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.url == f"https://{host}/"
    assert request.json() == {"NextToken": "page-2"}
    assert request.headers["x-amz-target"] == "StarlingDoveService.DescribeConfigRules"
    assert request.headers["content-type"] == "application/x-amz-json-1.1"
    authorization = request.headers["authorization"]
    assert authorization.startswith("AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/")
    assert f"/{signing_region}/config/aws4_request" in authorization
    assert "x-amz-target" in authorization
    assert request.headers["x-amz-date"]
    assert request.headers.get("x-amz-security-token") == token
    assert request.read_timeout == 60
    options = network.session_options[0]
    assert "example-secret" in options["redact_values"]
    if token:
        assert token in options["redact_values"]
    retry_policy = options["retry"]
    assert retry_policy.is_retry("POST", 503)
    assert retry_policy.is_retry("POST", 429)
    assert not retry_policy.is_retry("POST", 400)

    with scripted_network(
        [ScriptedResponse(status=302, headers={"Location": "https://example.com/"})]
    ) as redirect_network:
        client = AwsConfigClient(make_config(region=region, aws_session_token=token), "2014-11-12")
        with pytest.raises(AwsConfigError):
            client.request("DescribeConfigRules", {})
        client.close()
    assert len(redirect_network.requests_log) == 1


@pytest.mark.parametrize(
    "endpoint,result_key,operation,item,expected_key,limit",
    [
        (
            "resources",
            "Results",
            "SelectResourceConfig",
            '{"accountId":"111111111111","awsRegion":"eu-west-1","resourceType":"AWS::EC2::Instance","resourceId":"i-example","configuration":{"state":{"name":"running"}},"configurationItemCaptureTime":"2025-01-01T00:00:00Z"}',
            "resource_id",
            100,
        ),
        (
            "config_rules",
            "ConfigRules",
            "DescribeConfigRules",
            {"ConfigRuleArn": "arn:example:rule"},
            "config_rule_arn",
            None,
        ),
        (
            "rule_compliance",
            "ComplianceByConfigRules",
            "DescribeComplianceByConfigRule",
            {"ConfigRuleName": "example-rule", "Compliance": {"ComplianceType": "NON_COMPLIANT"}},
            "config_rule_name",
            None,
        ),
        (
            "conformance_packs",
            "ConformancePackDetails",
            "DescribeConformancePacks",
            {"ConformancePackArn": "arn:example:pack", "LastUpdateRequestedTime": 1735689600},
            "conformance_pack_arn",
            20,
        ),
        (
            "conformance_pack_compliance_scores",
            "ConformancePackComplianceScores",
            "ListConformancePackComplianceScores",
            {"ConformancePackName": "example-pack", "Score": "87.5", "LastUpdatedTime": 1735689600},
            "conformance_pack_name",
            20,
        ),
    ],
)
def test_full_refresh_paginates_through_empty_and_terminal_pages(
    session: MagicMock, endpoint: str, result_key: str, operation: str, item: Any, expected_key: str, limit: int | None
) -> None:
    session.post.side_effect = [
        make_response({result_key: [item], "NextToken": "second"}),
        make_response({result_key: [], "NextToken": "third"}),
        make_response({result_key: [item]}),
    ]
    manager = make_manager()
    response = aws_config_source(make_config(), endpoint, "2014-11-12", manager)
    batches = list(cast(Iterable[Any], response.items()))

    assert len(batches) == 2
    assert all(expected_key in batch[0] for batch in batches)
    assert all(batch[0]["region"] == "eu-west-1" for batch in batches)
    assert all(key in batches[0][0] for key in response.primary_keys or [])
    if endpoint == "resources":
        assert batches[0][0]["configuration"] == {"state": {"name": "running"}}
        assert batches[0][0]["configuration_item_capture_time"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    if endpoint == "conformance_packs":
        assert batches[0][0]["last_update_requested_time"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    if endpoint == "conformance_pack_compliance_scores":
        assert batches[0][0]["last_updated_time"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    if endpoint == "rule_compliance":
        assert batches[0][0]["compliance"] == {"ComplianceType": "NON_COMPLIANT"}
    for call, token in zip(session.post.call_args_list, [None, "second", "third"], strict=True):
        payload = json.loads(call.kwargs["data"])
        expected: dict[str, Any] = {}
        if limit is not None:
            expected["Limit"] = limit
        if endpoint == "resources":
            expected["Expression"] = (
                "SELECT accountId, awsRegion, arn, resourceId, resourceType, resourceName, "
                "configuration, configurationItemCaptureTime, resourceCreationTime, tags"
            )
        if token:
            expected["NextToken"] = token
        assert payload == expected
        assert call.kwargs["headers"]["X-Amz-Target"] == f"StarlingDoveService.{operation}"
    assert [call.args[0] for call in manager.save_state.call_args_list] == [
        AwsConfigResumeConfig(next_token="second"),
        AwsConfigResumeConfig(next_token="third"),
        AwsConfigResumeConfig(complete=True),
    ]
    assert manager.safe_point.call_count == 3
    manager.clear_state.assert_called_once()
    session.close.assert_called_once()


FAN_OUT_CASES = [
    (
        "rule_evaluation_results",
        ("DescribeConfigRules", "ConfigRules", "ConfigRuleName", None),
        ("GetComplianceDetailsByConfigRule", "EvaluationResults"),
        {"ComplianceTypes": ["COMPLIANT", "NON_COMPLIANT", "NOT_APPLICABLE"], "Limit": 100},
        lambda parent, index: {
            "EvaluationResultIdentifier": {
                "EvaluationResultQualifier": {
                    "ConfigRuleName": parent,
                    "ResourceType": "AWS::S3::Bucket",
                    "ResourceId": f"bucket-{index}",
                    "EvaluationMode": "DETECTIVE",
                },
                "OrderingTimestamp": 1735689600,
            },
            "ComplianceType": "NON_COMPLIANT",
            "ResultRecordedTime": 1735689600,
        },
    ),
    (
        "aggregated_resources",
        ("DescribeConfigurationAggregators", "ConfigurationAggregators", "ConfigurationAggregatorName", 100),
        ("SelectAggregateResourceConfig", "Results"),
        {
            "Limit": 100,
            "Expression": (
                "SELECT accountId, awsRegion, arn, resourceId, resourceType, resourceName, "
                "configuration, configurationItemCaptureTime, resourceCreationTime, tags"
            ),
        },
        lambda parent, index: json.dumps(
            {
                "accountId": "111111111111",
                "awsRegion": "us-west-2",
                "resourceType": "AWS::S3::Bucket",
                "resourceId": f"bucket-{index}",
                "configurationItemCaptureTime": "2025-01-01T00:00:00Z",
            }
        ),
    ),
    (
        "conformance_pack_evaluation_results",
        ("DescribeConformancePacks", "ConformancePackDetails", "ConformancePackName", 20),
        ("GetConformancePackComplianceDetails", "ConformancePackRuleEvaluationResults"),
        {"Limit": 100},
        lambda parent, index: {
            "ComplianceType": "COMPLIANT",
            "EvaluationResultIdentifier": {
                "EvaluationResultQualifier": {
                    "ConfigRuleName": f"{parent}-rule",
                    "ResourceType": "AWS::S3::Bucket",
                    "ResourceId": f"bucket-{index}",
                },
                "OrderingTimestamp": 1735689600,
            },
            "ConfigRuleInvokedTime": 1735689600,
            "ResultRecordedTime": 1735689600,
        },
    ),
    (
        "remediation_execution_statuses",
        ("DescribeConfigRules", "ConfigRules", "ConfigRuleName", None),
        ("DescribeRemediationExecutionStatus", "RemediationExecutionStatuses"),
        {"Limit": 100},
        lambda parent, index: {
            "ResourceKey": {"resourceType": "AWS::S3::Bucket", "resourceId": f"bucket-{index}"},
            "State": "FAILED",
            "StepDetails": [{"Name": "step-1", "State": "FAILED", "ErrorMessage": "Example failure"}],
            "InvocationTime": 1735689600,
            "LastUpdatedTime": 1735689600,
        },
    ),
]


@pytest.mark.parametrize("endpoint,parent,child,child_params,make_item", FAN_OUT_CASES)
def test_fan_out_walks_every_parent_and_child_page(
    session: MagicMock, endpoint: str, parent: tuple, child: tuple, child_params: dict, make_item: Any
) -> None:
    parent_operation, parent_key, param, parent_limit = parent
    child_operation, child_key = child
    session.post.side_effect = [
        make_response({parent_key: [{param: "a"}, {param: "b"}], "NextToken": "parent-2"}),
        make_response({child_key: [make_item("a", 1)], "NextToken": "child-2"}),
        make_response({child_key: [make_item("a", 2)]}),
        make_response({child_key: []}),
        make_response({parent_key: [{param: "c"}]}),
        make_response({child_key: [make_item("c", 3)]}),
    ]
    manager = make_manager()
    response = aws_config_source(make_config(), endpoint, "2014-11-12", manager)
    batches = list(cast(Iterable[Any], response.items()))

    rows = [row for batch in batches for row in batch]
    assert [(row[aws_config.snake_case(param)], row["resource_id"]) for row in rows] == [
        ("a", "bucket-1"),
        ("a", "bucket-2"),
        ("c", "bucket-3"),
    ]
    assert all(row.get(key) is not None for row in rows for key in response.primary_keys or [])
    if endpoint in ("rule_evaluation_results", "conformance_pack_evaluation_results"):
        assert rows[0]["ordering_timestamp"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
        assert "evaluation_result_identifier" not in rows[0]
    if endpoint == "remediation_execution_statuses":
        assert rows[0]["invocation_time"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
        assert "resource_key" not in rows[0]
    parent_params = {} if parent_limit is None else {"Limit": parent_limit}
    expected_requests = [
        (parent_operation, parent_params),
        (child_operation, {**child_params, param: "a"}),
        (child_operation, {**child_params, param: "a", "NextToken": "child-2"}),
        (child_operation, {**child_params, param: "b"}),
        (parent_operation, {**parent_params, "NextToken": "parent-2"}),
        (child_operation, {**child_params, param: "c"}),
    ]
    assert [
        (call.kwargs["headers"]["X-Amz-Target"].split(".")[1], json.loads(call.kwargs["data"]))
        for call in session.post.call_args_list
    ] == expected_requests
    assert [call.args[0] for call in manager.save_state.call_args_list] == [
        AwsConfigResumeConfig(parent_key="a", next_token="child-2"),
        AwsConfigResumeConfig(parent_key="b"),
        AwsConfigResumeConfig(parent_next_token="parent-2"),
        AwsConfigResumeConfig(complete=True),
    ]
    assert manager.safe_point.call_count == 4
    manager.clear_state.assert_called_once()


def test_fan_out_resumes_at_saved_parent(session: MagicMock) -> None:
    session.post.side_effect = [
        make_response({"ConfigRules": [{"ConfigRuleName": "a"}, {"ConfigRuleName": "b"}]}),
        make_response({"EvaluationResults": []}),
    ]
    manager = make_manager(AwsConfigResumeConfig(parent_next_token="parent-2", parent_key="b", next_token="child-2"))
    list(
        cast(Iterable[Any], aws_config_source(make_config(), "rule_evaluation_results", "2014-11-12", manager).items())
    )

    payloads = [json.loads(call.kwargs["data"]) for call in session.post.call_args_list]
    assert payloads[0] == {"NextToken": "parent-2"}
    assert [(payload["ConfigRuleName"], payload.get("NextToken")) for payload in payloads[1:]] == [("b", "child-2")]
    manager.clear_state.assert_called_once()


def history_item(resource_id: str, state: str) -> dict[str, Any]:
    return {
        "accountId": "111111111111",
        "awsRegion": "eu-west-1",
        "resourceType": "AWS::S3::Bucket",
        "resourceId": resource_id,
        "configurationStateId": state,
        "configurationItemStatus": "OK",
        "configurationItemCaptureTime": 1735689600,
        "configuration": '{"versioning":"Enabled"}',
    }


def test_resource_history_walks_composite_parent_keys_and_skips_undiscovered(session: MagicMock) -> None:
    resource = '{{"resourceType":"AWS::{0}","resourceId":"{1}"}}'
    session.post.side_effect = [
        make_response(
            {
                "Results": [resource.format("S3::Bucket", "bucket-1"), resource.format("S3::Bucket", "bucket-2")],
                "NextToken": "parent-2",
            }
        ),
        make_response({"configurationItems": [history_item("bucket-1", "3")], "nextToken": "history-2"}),
        make_response({"configurationItems": [history_item("bucket-1", "2")]}),
        make_response({"__type": "ResourceNotDiscoveredException", "message": "Unknown resource"}, 400),
        make_response({"Results": [resource.format("S3::Bucket", "bucket-3")]}),
        make_response({"configurationItems": [history_item("bucket-3", "1")]}),
    ]
    manager = make_manager()
    response = aws_config_source(
        make_config(), "resource_config_history", "2014-11-12", manager, True, dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    )
    rows = [row for batch in cast(Iterable[Any], response.items()) for row in batch]

    assert [(row["resource_id"], row["configuration_state_id"]) for row in rows] == [
        ("bucket-1", "3"),
        ("bucket-1", "2"),
        ("bucket-3", "1"),
    ]
    assert rows[0]["configuration_item_capture_time"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    assert all(row.get(key) is not None for row in rows for key in response.primary_keys or [])
    assert response.partition_keys == ["configuration_item_capture_time"]
    child = {"limit": 100, "earlierTime": 1735689600.0, "resourceType": "AWS::S3::Bucket"}
    assert [
        (call.kwargs["headers"]["X-Amz-Target"].split(".")[1], json.loads(call.kwargs["data"]))
        for call in session.post.call_args_list
    ] == [
        ("SelectResourceConfig", {"Limit": 100, "Expression": "SELECT resourceType, resourceId"}),
        ("GetResourceConfigHistory", {**child, "resourceId": "bucket-1"}),
        ("GetResourceConfigHistory", {**child, "resourceId": "bucket-1", "nextToken": "history-2"}),
        ("GetResourceConfigHistory", {**child, "resourceId": "bucket-2"}),
        (
            "SelectResourceConfig",
            {"Limit": 100, "Expression": "SELECT resourceType, resourceId", "NextToken": "parent-2"},
        ),
        ("GetResourceConfigHistory", {**child, "resourceId": "bucket-3"}),
    ]
    assert [call.args[0] for call in manager.save_state.call_args_list] == [
        AwsConfigResumeConfig(parent_key='["AWS::S3::Bucket", "bucket-1"]', next_token="history-2", since=1735689600.0),
        AwsConfigResumeConfig(parent_key='["AWS::S3::Bucket", "bucket-2"]', since=1735689600.0),
        AwsConfigResumeConfig(parent_next_token="parent-2", since=1735689600.0),
        AwsConfigResumeConfig(complete=True),
    ]


@time_machine.travel(dt.datetime(2025, 4, 1, tzinfo=dt.UTC), tick=False)
@pytest.mark.parametrize(
    "endpoint,should_use_incremental_field,last_value,expected_filter",
    [
        (
            "resource_evaluations",
            True,
            dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
            {"Filters": {"TimeWindow": {"StartTime": 1735689600.0}}},
        ),
        (
            "resource_evaluations",
            True,
            "2025-01-01T00:00:00Z",
            {"Filters": {"TimeWindow": {"StartTime": 1735689600.0}}},
        ),
        ("resource_evaluations", True, None, {}),
        ("resource_evaluations", False, dt.datetime(2025, 1, 1, tzinfo=dt.UTC), {}),
        ("resource_config_history", True, dt.datetime(2025, 1, 1), {"earlierTime": 1735689600.0}),
        ("resource_config_history", True, dt.date(2025, 1, 1), {"earlierTime": 1735689600.0}),
        ("resource_config_history", False, dt.datetime(2025, 3, 1, tzinfo=dt.UTC), {"earlierTime": 1735689600.0}),
        ("resource_config_history", True, None, {"earlierTime": 1735689600.0}),
        ("config_rules", True, dt.datetime(2025, 1, 1, tzinfo=dt.UTC), {}),
    ],
)
def test_incremental_start_shapes_request(
    session: MagicMock,
    endpoint: str,
    should_use_incremental_field: bool,
    last_value: Any,
    expected_filter: dict[str, Any],
) -> None:
    parent_page = make_response({"Results": ['{"resourceType":"AWS::S3::Bucket","resourceId":"bucket-1"}']})
    pages = [make_response({})]
    session.post.side_effect = [parent_page, *pages] if endpoint == "resource_config_history" else pages
    manager = make_manager()
    response = aws_config_source(
        make_config(), endpoint, "2014-11-12", manager, should_use_incremental_field, last_value
    )
    list(cast(Iterable[Any], response.items()))

    payload = json.loads(session.post.call_args_list[-1].kwargs["data"])
    for key in ("Limit", "limit", "resourceType", "resourceId", "Expression"):
        payload.pop(key, None)
    assert payload == expected_filter


def test_resume_keeps_incremental_start_of_interrupted_attempt(session: MagicMock) -> None:
    session.post.side_effect = [
        make_response(
            {
                "Results": [
                    '{"resourceType":"AWS::S3::Bucket","resourceId":"bucket-1"}',
                    '{"resourceType":"AWS::S3::Bucket","resourceId":"bucket-2"}',
                ]
            }
        ),
        make_response({"configurationItems": []}),
    ]
    manager = make_manager(
        AwsConfigResumeConfig(parent_key='["AWS::S3::Bucket", "bucket-2"]', next_token="history-2", since=1735689600.0)
    )
    response = aws_config_source(
        make_config(), "resource_config_history", "2014-11-12", manager, True, dt.datetime(2025, 2, 1, tzinfo=dt.UTC)
    )
    list(cast(Iterable[Any], response.items()))

    payloads = [json.loads(call.kwargs["data"]) for call in session.post.call_args_list]
    assert payloads[1] == {
        "limit": 100,
        "earlierTime": 1735689600.0,
        "resourceType": "AWS::S3::Bucket",
        "resourceId": "bucket-2",
        "nextToken": "history-2",
    }
    manager.clear_state.assert_called_once()


def test_fan_out_missing_saved_parent_clears_state_and_fails_attempt(session: MagicMock) -> None:
    session.post.return_value = make_response({"ConfigRules": [{"ConfigRuleName": "a"}]})
    manager = make_manager(AwsConfigResumeConfig(parent_key="deleted", next_token="child-2"))
    response = aws_config_source(make_config(), "rule_evaluation_results", "2014-11-12", manager)

    with pytest.raises(ValueError, match="changed during the sync"):
        list(cast(Iterable[Any], response.items()))

    session.post.assert_called_once()
    manager.clear_state.assert_called_once()
    manager.save_state.assert_not_called()


def test_expired_resume_token_clears_state_and_fails_attempt(session: MagicMock) -> None:
    session.post.return_value = make_response({"__type": "InvalidNextTokenException"}, 400)
    manager = make_manager(AwsConfigResumeConfig(next_token="expired-token"))
    response = aws_config_source(make_config(), "config_rules", "2014-11-12", manager)

    with pytest.raises(AwsConfigError, match="InvalidNextTokenException"):
        list(cast(Iterable[Any], response.items()))

    assert json.loads(session.post.call_args.kwargs["data"]) == {"NextToken": "expired-token"}
    manager.clear_state.assert_called_once()
    session.close.assert_called_once()


def test_checkpoint_is_staged_before_yield_and_session_closes_on_interruption(session: MagicMock) -> None:
    session.post.return_value = make_response(
        {"ConfigRules": [{"ConfigRuleArn": "arn:example:rule"}], "NextToken": "next"}
    )
    manager = make_manager()
    rows = aws_config.get_rows(make_config(), aws_config.AWS_CONFIG_ENDPOINTS["config_rules"], "2014-11-12", manager)
    next(rows)
    manager.save_state.assert_called_once_with(AwsConfigResumeConfig(next_token="next"))
    manager.safe_point.assert_not_called()
    rows.close()
    session.close.assert_called_once()
    manager.clear_state.assert_not_called()


def test_completed_resume_does_not_repeat_requests() -> None:
    result = SourceDriver(AwsConfigSource(), make_config()).run(
        "config_rules", [], resume_state=AwsConfigResumeConfig(complete=True)
    )

    assert result.raised is None
    assert result.rows == []
    assert result.final_state is None
    assert result.requests == []


@pytest.mark.parametrize("token", ["saved-token", 123])
def test_invalid_page_token_does_not_advance_checkpoint(session: MagicMock, token: Any) -> None:
    session.post.return_value = make_response({"ConfigRules": [], "NextToken": token})
    manager = make_manager(AwsConfigResumeConfig(next_token="saved-token"))
    with pytest.raises(ValueError, match="invalid page token"):
        list(cast(Iterable[Any], aws_config_source(make_config(), "config_rules", "2014-11-12", manager).items()))
    manager.save_state.assert_not_called()
    session.close.assert_called_once()


@pytest.mark.parametrize("body", [{"Results": ["not JSON"]}, {"Results": ["[]"]}, []])
def test_malformed_results_do_not_advance_checkpoint(session: MagicMock, body: Any) -> None:
    session.post.return_value = make_response(body)
    manager = make_manager()
    with pytest.raises(ValueError):
        list(cast(Iterable[Any], aws_config_source(make_config(), "resources", "2014-11-12", manager).items()))
    manager.save_state.assert_not_called()
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "status,body,headers,code,throttled",
    [
        (400, {"__type": "com.amazonaws.config#ThrottlingException"}, {}, "ThrottlingException", True),
        (400, {"code": "Throttling"}, {}, "Throttling", True),
        (429, {"__type": "ThrottlingException"}, {}, "ThrottlingException", False),
        (503, {"__type": "ServiceUnavailableException"}, {}, "ServiceUnavailableException", False),
        (
            403,
            {"Message": "Denied"},
            {"x-amzn-ErrorType": "AccessDeniedException:http"},
            "AccessDeniedException",
            False,
        ),
        (400, {"__type": "UnrecognizedClientException"}, {}, "UnrecognizedClientException", False),
        (502, [], {}, "HTTP 502", False),
    ],
)
def test_error_classification(status: int, body: Any, headers: dict[str, str], code: str, throttled: bool) -> None:
    error = aws_config.error_for_response(make_response(body, status, headers))
    assert error.code == code
    assert isinstance(error, AwsConfigThrottledError) is throttled


def test_body_throttles_retry_without_sleep() -> None:
    with scripted_network(
        [
            ScriptedResponse(status=400, json={"__type": "ThrottlingException", "message": "Rate exceeded"}),
            ScriptedResponse(json={"ConfigRules": []}),
        ]
    ) as network:
        client = AwsConfigClient(make_config(), "2014-11-12")
        assert client.request("DescribeConfigRules", {}) == {"ConfigRules": []}
        client.close()
    assert len(network.requests_log) == 2


@pytest.mark.parametrize("schema_name", [None, "config_rules"])
@pytest.mark.parametrize("code", ["AccessDenied", "AccessDeniedException"])
def test_access_denied_only_blocks_selected_table(session: MagicMock, schema_name: str | None, code: str) -> None:
    session.post.return_value = make_response({"__type": code, "message": "Access denied"}, 400)
    valid, reason = validate_credentials(make_config(), "2014-11-12", schema_name)
    assert valid is (schema_name is None)
    assert reason is None if schema_name is None else "config:DescribeConfigRules" in (reason or "")
    session.post.assert_called_once()
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "code,message",
    [
        ("UnrecognizedClientException", "Check the access key ID"),
        ("InvalidSignatureException", "Check the secret access key"),
        ("ExpiredTokenException", "expired"),
        ("OptInRequired", "Enable AWS Config"),
        ("SubscriptionRequiredException", "Enable AWS Config"),
        ("InternalError", "try again"),
    ],
)
def test_credential_errors_are_actionable(code: str, message: str) -> None:
    with scripted_network([ScriptedResponse(status=400, json={"__type": code, "message": "Vendor error"})]) as network:
        valid, reason = validate_credentials(make_config(), "2014-11-12")
    assert not valid
    assert message in (reason or "")
    assert len(network.requests_log) == 1


@pytest.mark.parametrize(
    "schema,responses,expected",
    [
        (None, [{}], [("DescribeConfigRules", None)]),
        ("resources", [{}], [("SelectResourceConfig", 1)]),
        ("conformance_packs", [{}], [("DescribeConformancePacks", 1)]),
        ("rule_evaluation_results", [{}], [("DescribeConfigRules", None)]),
        (
            "rule_evaluation_results",
            [{"ConfigRules": [{"ConfigRuleName": "example-rule"}]}, {}],
            [("DescribeConfigRules", None), ("GetComplianceDetailsByConfigRule", 1)],
        ),
        (
            "aggregated_resources",
            [{"ConfigurationAggregators": [{"ConfigurationAggregatorName": "example-aggregator"}]}, {}],
            [("DescribeConfigurationAggregators", 1), ("SelectAggregateResourceConfig", 1)],
        ),
        (
            "resource_config_history",
            [{"Results": ['{"resourceType":"AWS::S3::Bucket","resourceId":"example-bucket"}']}, {}],
            [("SelectResourceConfig", 1), ("GetResourceConfigHistory", 1)],
        ),
        (
            "remediation_execution_statuses",
            [
                {"ConfigRules": [{"ConfigRuleName": "example-rule"}]},
                ScriptedResponse(status=400, json={"__type": "NoSuchRemediationConfigurationException"}),
            ],
            [("DescribeConfigRules", None), ("DescribeRemediationExecutionStatus", 1)],
        ),
        ("resource_evaluations", [{}], [("ListResourceEvaluations", 1)]),
    ],
)
def test_credential_probe_reads_parent_then_one_child(
    schema: str | None, responses: list[Any], expected: list[tuple[str, int | None]]
) -> None:
    script = [body if isinstance(body, ScriptedResponse) else ScriptedResponse(json=body) for body in responses]
    with scripted_network(script) as network:
        assert validate_credentials(make_config(), "2014-11-12", schema) == (True, None)
    assert [
        (request.headers["x-amz-target"].split(".")[1], request.json().get("Limit", request.json().get("limit")))
        for request in network.requests_log
    ] == expected
    if len(expected) == 2:
        assert set(network.requests_log[1].json()) & {"ConfigRuleName", "ConfigurationAggregatorName", "resourceId"}


def test_fan_out_access_denied_names_child_permission() -> None:
    with scripted_network(
        [
            ScriptedResponse(json={"ConfigRules": [{"ConfigRuleName": "example-rule"}]}),
            ScriptedResponse(status=400, json={"__type": "AccessDeniedException", "message": "Denied"}),
        ]
    ):
        valid, reason = validate_credentials(make_config(), "2014-11-12", "rule_evaluation_results")
    assert not valid
    assert "config:GetComplianceDetailsByConfigRule" in (reason or "")


@pytest.mark.parametrize("region", ["https://example.com", "us-east-1.example.com/path", "us-east-1\n", "../us-east-1"])
def test_invalid_region_fails_before_transport(region: str) -> None:
    with scripted_network([]) as network:
        valid, reason = validate_credentials(make_config(region=region), "2014-11-12")
    assert not valid
    assert reason == "Enter an AWS region such as us-east-1."
    assert network.requests_log == []


@pytest.mark.parametrize("field", ["aws_access_key_id", "aws_secret_access_key"])
def test_missing_credentials_fail_before_transport(field: str) -> None:
    with scripted_network([]) as network:
        valid, reason = validate_credentials(make_config(**{field: ""}), "2014-11-12")
    assert not valid
    assert "Enter both" in (reason or "")
    assert network.requests_log == []


def test_unknown_table_and_version_fail_before_transport() -> None:
    with scripted_network([]) as network:
        assert validate_credentials(make_config(), "2014-11-12", "unknown") == (
            False,
            "Unknown AWS Config table: unknown",
        )
        valid, reason = validate_credentials(make_config(), "invalid-version")
    result = SourceDriver(AwsConfigSource(), make_config()).run("unknown", [])
    assert isinstance(result.raised, ValueError)
    assert "Unknown AWS Config table" in str(result.raised)
    assert not valid
    assert "Unsupported AWS Config API version" in (reason or "")
    assert network.requests_log == []
    assert result.requests == []


def test_network_failure_closes_probe_session(session: MagicMock) -> None:
    session.post.side_effect = requests.Timeout()
    valid, reason = validate_credentials(make_config(), "2014-11-12")
    assert not valid
    assert "try again" in (reason or "")
    session.close.assert_called_once()


def test_new_invalid_token_is_not_silently_restarted() -> None:
    result = SourceDriver(AwsConfigSource(), make_config()).run(
        "config_rules", [ScriptedResponse(status=400, json={"__type": "InvalidNextTokenException"})]
    )
    assert isinstance(result.raised, AwsConfigError)
    assert "InvalidNextTokenException" in str(result.raised)
    assert len(result.requests) == 1
