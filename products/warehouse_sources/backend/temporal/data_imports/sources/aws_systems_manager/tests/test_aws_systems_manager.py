import json
import datetime as dt
from collections.abc import Generator, Iterable, Iterator
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_systems_manager import (
    aws_systems_manager as transport,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_systems_manager.aws_systems_manager import (
    SystemsManagerClient,
    SystemsManagerError,
    SystemsManagerResumeConfig,
    SystemsManagerThrottledError,
    aws_systems_manager_source,
    error_for_response,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_systems_manager.settings import API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_systems_manager.source import (
    AwsSystemsManagerSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssystemsmanager import (
    AwsSystemsManagerSourceConfig,
)


def response(body: object, status: int = 200, headers: dict[str, str] | None = None) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    result.headers.update(headers or {})
    return result


def iter_batches(source: SourceResponse) -> Iterator[list[dict[str, Any]]]:
    return iter(cast(Iterable[list[dict[str, Any]]], source.items()))


def driver(config: AwsSystemsManagerSourceConfig) -> SourceDriver:
    return SourceDriver(AwsSystemsManagerSource(), config)


@pytest.fixture
def config() -> AwsSystemsManagerSourceConfig:
    return AwsSystemsManagerSourceConfig(
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="fake-secret",
        aws_region="eu-west-1",
        aws_session_token="fake-token",
    )


@pytest.fixture
def http() -> Iterator[MagicMock]:
    with patch.object(transport, "make_tracked_session") as factory:
        session = factory.return_value
        session.post.return_value = response({})
        yield session


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


@pytest.mark.parametrize(
    "region,host",
    [
        ("eu-west-1", "ssm.eu-west-1.amazonaws.com"),
        ("cn-north-1", "ssm.cn-north-1.amazonaws.com.cn"),
        ("us-gov-west-1", "ssm.us-gov-west-1.amazonaws.com"),
    ],
)
@pytest.mark.parametrize("token", [None, "fake-token"])
def test_signs_serialized_body_for_selected_region(
    config: AwsSystemsManagerSourceConfig, region: str, host: str, token: str | None
) -> None:
    config.aws_region = region
    config.aws_session_token = token
    with scripted_network(
        [ScriptedResponse(status=302, json={}, headers={"Location": "https://example.com/"})]
    ) as network:
        client = SystemsManagerClient(config, API_VERSION)
        assert client.request("DescribeInstanceInformation", {"MaxResults": 5}) == {}
        client.close()
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.url == f"https://{host}/"
    assert request.json() == {"MaxResults": 5}
    headers = request.headers
    assert headers["x-amz-target"] == "AmazonSSM.DescribeInstanceInformation"
    assert headers["content-type"] == "application/x-amz-json-1.1"
    assert headers.get("x-amz-security-token") == token
    assert f"/{region}/ssm/aws4_request" in headers["authorization"]
    assert "content-type;host;x-amz-date;" in headers["authorization"]
    assert "x-amz-target" in headers["authorization"]
    assert headers["x-amz-date"]
    assert request.read_timeout == 60
    assert config.aws_secret_access_key in network.session_options[0]["redact_values"]
    if token:
        assert token in network.session_options[0]["redact_values"]


@pytest.mark.parametrize(
    "region", ["", "https://example.com", "us-east-1.example.com", "../us-east-1", "us-east-1/path"]
)
def test_rejects_region_before_sending_credentials(config: AwsSystemsManagerSourceConfig, region: str) -> None:
    config.aws_region = region
    with scripted_network([]) as network:
        valid, reason = validate_credentials(config, API_VERSION)
    assert not valid and reason and "valid AWS region" in reason
    assert network.requests_log == []


def test_rejects_unsupported_model_version(config: AwsSystemsManagerSourceConfig) -> None:
    with scripted_network([]) as network:
        valid, reason = validate_credentials(config, "2099-01-01")
    assert not valid and reason and "Unsupported" in reason
    assert network.requests_log == []


@pytest.mark.parametrize(
    "name,operation,key,item,expected_key,page_size",
    [
        (
            "managed_instances",
            "DescribeInstanceInformation",
            "InstanceInformationList",
            {"InstanceId": "i-example"},
            "instance_id",
            50,
        ),
        ("inventory", "GetInventory", "Entities", {"Id": "i-example"}, "id", 50),
        (
            "resource_compliance_summaries",
            "ListResourceComplianceSummaries",
            "ResourceComplianceSummaryItems",
            {"ResourceId": "i-example", "ResourceType": "ManagedInstance", "ComplianceType": "Patch"},
            "resource_id",
            50,
        ),
        (
            "associations",
            "ListAssociations",
            "Associations",
            {"AssociationId": "association-example"},
            "association_id",
            50,
        ),
        (
            "patch_baselines",
            "DescribePatchBaselines",
            "BaselineIdentities",
            {"BaselineId": "pb-example"},
            "baseline_id",
            100,
        ),
        (
            "ops_item_events",
            "ListOpsItemEvents",
            "Summaries",
            {"EventId": "event-example", "OpsItemId": "oi-example"},
            "event_id",
            50,
        ),
    ],
)
@pytest.mark.parametrize("terminal_token", [None, ""])
def test_paginates_empty_and_terminal_pages(
    config: AwsSystemsManagerSourceConfig,
    http: MagicMock,
    manager: MagicMock,
    name: str,
    operation: str,
    key: str,
    item: dict[str, Any],
    expected_key: str,
    page_size: int,
    terminal_token: str | None,
) -> None:
    http.post.side_effect = [
        response({key: [], "NextToken": "next"}),
        response({key: [item], "NextToken": terminal_token}),
    ]
    source = aws_systems_manager_source(config, name, API_VERSION, manager)
    rows = [row for batch in iter_batches(source) for row in batch]
    assert len(rows) == 1
    assert rows[0][expected_key] == next(iter(item.values()))
    assert rows[0]["region"] == "eu-west-1"
    assert len({tuple(row[column] for column in source.primary_keys or []) for row in rows}) == 1
    calls = http.post.call_args_list
    expected: dict[str, Any] = {"MaxResults": page_size}
    if name == "inventory":
        expected["ResultAttributes"] = [{"TypeName": "AWS:InstanceInformation"}]
    assert json.loads(calls[0].kwargs["data"]) == expected
    assert json.loads(calls[1].kwargs["data"]) == {**expected, "NextToken": "next"}
    assert calls[0].kwargs["headers"]["X-Amz-Target"] == f"AmazonSSM.{operation}"
    assert manager.save_state.call_args_list[0].args[0] == SystemsManagerResumeConfig(next_token="next")
    assert manager.save_state.call_args_list[1].args[0] == SystemsManagerResumeConfig(completed=True)
    assert manager.safe_point.call_count == 2
    manager.clear_state.assert_not_called()
    assert source.on_complete is not None
    source.on_complete()
    manager.clear_state.assert_called_once()
    http.close.assert_called_once()


def test_resume_state_is_staged_before_yield(
    config: AwsSystemsManagerSourceConfig, http: MagicMock, manager: MagicMock
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = SystemsManagerResumeConfig(next_token="saved")
    http.post.return_value = response({"Associations": [{"AssociationId": "a-example"}], "NextToken": "later"})
    rows = cast(
        Generator[list[dict[str, Any]]],
        aws_systems_manager_source(config, "associations", API_VERSION, manager).items(),
    )
    assert next(rows)[0]["association_id"] == "a-example"
    assert json.loads(http.post.call_args.kwargs["data"]) == {"MaxResults": 50, "NextToken": "saved"}
    manager.save_state.assert_called_once_with(SystemsManagerResumeConfig(next_token="later"))
    rows.close()
    http.close.assert_called_once()


def test_completed_resume_does_not_restart_walk(
    config: AwsSystemsManagerSourceConfig,
) -> None:
    result = driver(config).run("associations", [], resume_state=SystemsManagerResumeConfig(completed=True))
    assert result.raised is None
    assert result.rows == []
    assert result.requests == []
    assert result.final_state == SystemsManagerResumeConfig(completed=True)


@pytest.mark.parametrize("resumed", [False, True])
def test_expired_token_restarts_only_saved_walk(config: AwsSystemsManagerSourceConfig, resumed: bool) -> None:
    script = [
        ScriptedResponse(
            status=400, json={"__type": "InvalidNextToken", "Message": "The specified token isn't valid."}
        ),
        ScriptedResponse(json={"Associations": [{"AssociationId": "a-example"}]}),
    ]
    result = driver(config).run(
        "associations",
        script,
        resume_state=SystemsManagerResumeConfig(next_token="expired") if resumed else None,
    )
    if resumed:
        assert result.raised is None
        assert result.rows[0]["association_id"] == "a-example"
        assert [request.json() for request in result.requests] == [
            {"MaxResults": 50, "NextToken": "expired"},
            {"MaxResults": 50},
        ]
    else:
        assert isinstance(result.raised, SystemsManagerError)
        assert "InvalidNextToken" in str(result.raised)
        assert len(result.requests) == 1
        assert result.requests[0].json() == {"MaxResults": 50}


@pytest.mark.parametrize("token", ["same", 123])
def test_invalid_pagination_fails_without_loop(config: AwsSystemsManagerSourceConfig, token: object) -> None:
    result = driver(config).run(
        "associations",
        [ScriptedResponse(json={"NextToken": token})],
        resume_state=SystemsManagerResumeConfig(next_token="same"),
    )
    assert isinstance(result.raised, ValueError)
    assert "invalid or repeated page token" in str(result.raised)
    assert len(result.requests) == 1
    assert result.saved_states == []
    assert result.final_state == SystemsManagerResumeConfig(next_token="same")


@pytest.mark.parametrize(
    "code,fragment",
    [
        ("UnrecognizedClientException", "Check the access key"),
        ("InvalidClientTokenId", "active"),
        ("InvalidSignatureException", "signature"),
        ("SignatureDoesNotMatch", "signature"),
        ("ExpiredTokenException", "expired"),
        ("ExpiredToken", "expired"),
        ("SubscriptionRequiredException", "Enable AWS Systems Manager"),
        ("OptInRequired", "Enable AWS Systems Manager"),
    ],
)
def test_authentication_errors_are_terminal_and_actionable(
    config: AwsSystemsManagerSourceConfig, code: str, fragment: str
) -> None:
    body = {"__type": f"com.amazonaws.ssm#{code}", "message": "Rejected"}
    with scripted_network([ScriptedResponse(status=400, json=body)]) as network:
        valid, reason = validate_credentials(config, API_VERSION)
    assert not valid and reason and fragment in reason
    error = error_for_response(response(body, 400))
    matches = [
        message
        for pattern, message in AwsSystemsManagerSource().get_non_retryable_errors().items()
        if pattern in str(error)
    ]
    assert reason in matches
    assert len(network.requests_log) == 1


@pytest.mark.parametrize("code", ["AccessDenied", "AccessDeniedException"])
@pytest.mark.parametrize("schema,expected", [(None, True), ("inventory", False)])
def test_permission_denial_only_allows_source_creation(
    config: AwsSystemsManagerSourceConfig, code: str, schema: str | None, expected: bool
) -> None:
    with scripted_network([ScriptedResponse(status=400, json={"__type": code, "Message": "Access denied"})]) as network:
        valid, reason = validate_credentials(config, API_VERSION, schema)
    assert valid is expected
    assert reason is None if expected else reason == "Grant ssm:GetInventory to read this table."
    assert len(network.requests_log) == 1


@pytest.mark.parametrize(
    "schema,operation,size",
    [
        (None, "DescribeInstanceInformation", 5),
        ("inventory", "GetInventory", 1),
        ("patch_baselines", "DescribePatchBaselines", 1),
    ],
)
def test_validation_uses_one_small_request(
    config: AwsSystemsManagerSourceConfig, http: MagicMock, schema: str | None, operation: str, size: int
) -> None:
    assert validate_credentials(config, API_VERSION, schema) == (True, None)
    assert http.post.call_count == 1
    assert json.loads(http.post.call_args.kwargs["data"])["MaxResults"] == size
    assert http.post.call_args.kwargs["headers"]["X-Amz-Target"] == f"AmazonSSM.{operation}"
    http.close.assert_called_once()


@pytest.mark.parametrize("field", ["aws_access_key_id", "aws_secret_access_key"])
def test_missing_credentials_do_not_send_request(config: AwsSystemsManagerSourceConfig, field: str) -> None:
    setattr(config, field, "")
    with scripted_network([]) as network:
        valid, reason = validate_credentials(config, API_VERSION)
    assert not valid and reason and "Enter both" in reason
    assert network.requests_log == []


def test_unknown_table_fails_before_request(
    config: AwsSystemsManagerSourceConfig,
) -> None:
    with scripted_network([]) as network:
        valid, reason = validate_credentials(config, API_VERSION, "unknown")
    assert not valid and reason and "Unknown" in reason
    result = driver(config).run("unknown", [])
    assert isinstance(result.raised, ValueError)
    assert "Unknown AWS Systems Manager table" in str(result.raised)
    assert network.requests_log == []
    assert result.requests == []


@pytest.mark.parametrize(
    "status,body,headers,code",
    [
        (400, {"__type": "com.amazonaws.ssm#AccessDeniedException", "Message": "denied"}, {}, "AccessDeniedException"),
        (403, {}, {"x-amzn-ErrorType": "InvalidSignatureException:detail"}, "InvalidSignatureException"),
        (400, {"code": "OptInRequired"}, {}, "OptInRequired"),
        (502, [], {}, "HTTP 502"),
    ],
)
def test_decodes_aws_errors(status: int, body: object, headers: dict[str, str], code: str) -> None:
    error = error_for_response(response(body, status, headers))
    assert error.code == code
    assert not isinstance(error, SystemsManagerThrottledError)


@pytest.mark.parametrize("code", ["Throttling", "ThrottlingException", "TooManyRequestsException"])
def test_retries_body_throttling(config: AwsSystemsManagerSourceConfig, code: str) -> None:
    with scripted_network(
        [ScriptedResponse(status=400, json={"__type": code}), ScriptedResponse(json={"Associations": []})]
    ) as network:
        client = SystemsManagerClient(config, API_VERSION)
        assert client.request("ListAssociations", {"MaxResults": 50}) == {"Associations": []}
        client.close()
    assert len(network.requests_log) == 2


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_status_retries_belong_only_to_tracked_transport(config: AwsSystemsManagerSourceConfig, status: int) -> None:
    with scripted_network(always(ScriptedResponse(status=status, json={"__type": "InternalServerError"}))) as network:
        client = SystemsManagerClient(config, API_VERSION)
        with pytest.raises(SystemsManagerError):
            client.request("ListAssociations", {"MaxResults": 50})
        client.close()
    assert len(network.requests_log) > 1
    assert {request.path for request in network.requests_log} == {"/"}
    assert network.session_options[0]["retry"].is_retry("POST", status)


def test_normalizes_nested_counts_timestamps_and_composite_keys(
    config: AwsSystemsManagerSourceConfig,
) -> None:
    result = driver(config).run(
        "resource_compliance_summaries",
        [
            ScriptedResponse(
                json={
                    "ResourceComplianceSummaryItems": [
                        {
                            "ResourceId": "i-example",
                            "ResourceType": "ManagedInstance",
                            "ComplianceType": compliance,
                            "CompliantSummary": {"CompliantCount": 2},
                            "ExecutionSummary": {"ExecutionTime": 1735689600},
                        }
                        for compliance in ["Patch", "Association"]
                    ]
                }
            )
        ],
    )
    assert result.raised is None
    assert result.response is not None
    rows = result.rows
    assert len({tuple(row[key] for key in result.response.primary_keys or []) for row in rows}) == 2
    assert rows[0]["compliant_summary_compliant_count"] == 2
    assert rows[0]["execution_summary_execution_time"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    "schema,result_key,item_id,key,column,data",
    [
        (
            "inventory",
            "Entities",
            {"Id": "i-example"},
            "Data",
            "data",
            {
                "AWS:InstanceInformation": {
                    "CaptureTime": "2025-01-01T00:00:00Z",
                    "Content": [{"InstanceId": "i-example", "InstanceStatus": "Stopped"}],
                }
            },
        ),
        (
            "ops_items",
            "OpsItemSummaries",
            {"OpsItemId": "oi-example"},
            "OperationalData",
            "operational_data",
            {"/aws/resources": {"Value": '[{"arn": "arn:aws:ec2:example"}]', "Type": "SearchableString"}},
        ),
    ],
)
def test_preserves_dynamic_content_as_json(
    config: AwsSystemsManagerSourceConfig,
    schema: str,
    result_key: str,
    item_id: dict[str, Any],
    key: str,
    column: str,
    data: dict[str, Any],
) -> None:
    result = driver(config).run(schema, [ScriptedResponse(json={result_key: [{**item_id, key: data}]})])
    assert result.raised is None
    assert len(result.rows) == 1
    assert json.loads(result.rows[0][column]) == data
    assert not any(name.startswith(f"{column}_") for name in result.rows[0])


@pytest.mark.parametrize("incremental", [False, True])
def test_snapshot_requests_never_filter_by_watermark(
    config: AwsSystemsManagerSourceConfig, http: MagicMock, manager: MagicMock, incremental: bool
) -> None:
    inputs = SourceInputs(
        schema_name="managed_instances",
        schema_id="schema",
        source_id="source",
        team_id=1,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
        db_incremental_field_earliest_value=None,
        incremental_field="last_ping_date_time",
        incremental_field_type=None,
        job_id="job",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )
    list(iter_batches(AwsSystemsManagerSource().source_for_pipeline(config, manager, inputs)))
    assert json.loads(http.post.call_args.kwargs["data"]) == {"MaxResults": 50}


def _error(code: str) -> ScriptedResponse:
    return ScriptedResponse(status=400, json={"__type": code, "Message": "Not found"})


def _key(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


def _instance(instance_id: str, status: str) -> dict[str, Any]:
    return {"Id": instance_id, "Data": {"AWS:InstanceInformation": {"Content": [{"InstanceStatus": status}]}}}


@pytest.mark.parametrize(
    "schema,script,expected_requests,expected_rows",
    [
        (
            "compliance_items",
            [
                ScriptedResponse(
                    json={
                        "ResourceComplianceSummaryItems": [
                            {"ResourceId": "i-a", "ResourceType": "ManagedInstance", "ComplianceType": "Patch"},
                            {"ResourceId": "i-gone", "ResourceType": "ManagedInstance", "ComplianceType": "Patch"},
                        ]
                    }
                ),
                ScriptedResponse(
                    json={
                        "ComplianceItems": [
                            {
                                "ResourceId": "i-a",
                                "ResourceType": "ManagedInstance",
                                "ComplianceType": "Patch",
                                "Id": "KB1",
                                "Status": "NON_COMPLIANT",
                                "Details": {"PatchState": "Missing"},
                                "ExecutionSummary": {"ExecutionTime": 1735689600},
                            }
                        ]
                    }
                ),
                _error("InvalidResourceId"),
            ],
            [
                ("ListResourceComplianceSummaries", {"MaxResults": 50}),
                *(
                    (
                        "ListComplianceItems",
                        {
                            "MaxResults": 50,
                            "ResourceIds": [resource_id],
                            "ResourceTypes": ["ManagedInstance"],
                            "Filters": [{"Key": "ComplianceType", "Values": ["Patch"], "Type": "EQUAL"}],
                        },
                    )
                    for resource_id in ["i-a", "i-gone"]
                ),
            ],
            [
                {
                    "resource_id": "i-a",
                    "id": "KB1",
                    "details_patch_state": "Missing",
                    "execution_summary_execution_time": dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
                }
            ],
        ),
        (
            "inventory_entries",
            [
                ScriptedResponse(
                    json={
                        "Schemas": [
                            {"TypeName": name} for name in ["AWS:Service", "AWS:InstanceInformation", "AWS:Application"]
                        ]
                    }
                ),
                ScriptedResponse(
                    json={"Entities": [_instance("i-0123456789abcdef0", "Active"), _instance("i-ended", "Terminated")]}
                ),
                ScriptedResponse(
                    json={
                        "InstanceId": "i-0123456789abcdef0",
                        "TypeName": "AWS:Application",
                        "SchemaVersion": "1.1",
                        "CaptureTime": "2025-01-01T00:00:00Z",
                        "Entries": [{"Name": "nginx", "Version": "1.0"}, {"Name": "curl", "Version": "8.0"}],
                    }
                ),
                _error("InvalidInstanceId"),
            ],
            [
                ("GetInventorySchema", {"MaxResults": 200}),
                ("GetInventory", {"MaxResults": 50, "ResultAttributes": [{"TypeName": "AWS:InstanceInformation"}]}),
                *(
                    ("ListInventoryEntries", {"MaxResults": 50, "InstanceId": "i-0123456789abcdef0", "TypeName": name})
                    for name in ["AWS:Application", "AWS:Service"]
                ),
            ],
            [
                {
                    "instance_id": "i-0123456789abcdef0",
                    "type_name": "AWS:Application",
                    "capture_time": dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
                    "entry": json.dumps({"Name": name, "Version": version}, sort_keys=True),
                }
                for name, version in [("nginx", "1.0"), ("curl", "8.0")]
            ],
        ),
        (
            "association_execution_targets",
            [
                ScriptedResponse(json={"Associations": [{"AssociationId": "a-1"}]}),
                ScriptedResponse(
                    json={
                        "AssociationExecutions": [
                            {"AssociationId": "a-1", "ExecutionId": "e-1"},
                            {"AssociationId": "a-1", "ExecutionId": "e-gone"},
                        ]
                    }
                ),
                ScriptedResponse(
                    json={
                        "AssociationExecutionTargets": [
                            {
                                "AssociationId": "a-1",
                                "ExecutionId": "e-1",
                                "ResourceId": "i-a",
                                "ResourceType": "ManagedInstance",
                                "Status": "Failed",
                                "LastExecutionDate": 1735689600,
                            }
                        ]
                    }
                ),
                _error("AssociationExecutionDoesNotExist"),
            ],
            [
                ("ListAssociations", {"MaxResults": 50}),
                ("DescribeAssociationExecutions", {"MaxResults": 50, "AssociationId": "a-1"}),
                *(
                    (
                        "DescribeAssociationExecutionTargets",
                        {"MaxResults": 50, "AssociationId": "a-1", "ExecutionId": execution_id},
                    )
                    for execution_id in ["e-1", "e-gone"]
                ),
            ],
            [
                {
                    "execution_id": "e-1",
                    "resource_id": "i-a",
                    "status": "Failed",
                    "last_execution_date": dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
                }
            ],
        ),
        (
            "instance_patch_states",
            [
                ScriptedResponse(
                    json={
                        "InstanceInformationList": [{"InstanceId": "i-a"}, {"InstanceId": "mi-b"}],
                        "NextToken": "nodes-2",
                    }
                ),
                ScriptedResponse(
                    json={
                        "InstancePatchStates": [
                            {"InstanceId": "i-a", "MissingCount": 3, "OperationEndTime": 1735689600},
                            {"InstanceId": "mi-b", "MissingCount": 0, "OperationEndTime": 1735689600},
                        ]
                    }
                ),
                ScriptedResponse(json={"InstanceInformationList": [{"InstanceId": "i-c"}]}),
                ScriptedResponse(json={"InstancePatchStates": [{"InstanceId": "i-c", "MissingCount": 1}]}),
            ],
            [
                ("DescribeInstanceInformation", {"MaxResults": 50}),
                ("DescribeInstancePatchStates", {"MaxResults": 50, "InstanceIds": ["i-a", "mi-b"]}),
                ("DescribeInstanceInformation", {"MaxResults": 50, "NextToken": "nodes-2"}),
                ("DescribeInstancePatchStates", {"MaxResults": 50, "InstanceIds": ["i-c"]}),
            ],
            [
                {
                    "instance_id": "i-a",
                    "missing_count": 3,
                    "operation_end_time": dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
                },
                {"instance_id": "mi-b", "missing_count": 0},
                {"instance_id": "i-c", "missing_count": 1},
            ],
        ),
        (
            "instance_patches",
            [
                ScriptedResponse(json={"InstanceInformationList": [{"InstanceId": "i-a"}, {"InstanceId": "i-gone"}]}),
                ScriptedResponse(
                    json={
                        "Patches": [
                            {"Title": "KB1 update", "KBId": "KB1", "State": "Missing", "InstalledTime": 0},
                            {"Title": "KB2 update", "KBId": "KB2", "State": "Installed", "InstalledTime": 1735689600},
                        ]
                    }
                ),
                _error("InvalidInstanceId"),
            ],
            [
                ("DescribeInstanceInformation", {"MaxResults": 50}),
                *(
                    ("DescribeInstancePatches", {"MaxResults": 100, "InstanceId": instance_id})
                    for instance_id in ["i-a", "i-gone"]
                ),
            ],
            [
                {"instance_id": "i-a", "kb_id": "KB1", "state": "Missing"},
                {
                    "instance_id": "i-a",
                    "kb_id": "KB2",
                    "state": "Installed",
                    "installed_time": dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
                },
            ],
        ),
    ],
)
def test_fan_out_requests_each_parent_row_and_skips_vanished_parents(
    config: AwsSystemsManagerSourceConfig,
    schema: str,
    script: list[ScriptedResponse],
    expected_requests: list[tuple[str, dict[str, Any]]],
    expected_rows: list[dict[str, Any]],
) -> None:
    result = driver(config).run(schema, script)
    assert result.raised is None
    assert [
        (request.headers["x-amz-target"].removeprefix("AmazonSSM."), request.json()) for request in result.requests
    ] == expected_requests
    assert [{key: row[key] for key in expected} for row, expected in zip(result.rows, expected_rows)] == expected_rows
    assert len(result.rows) == len(expected_rows)
    assert result.response is not None
    keys = {tuple(row[column] for column in result.response.primary_keys or []) for row in result.rows}
    assert len(keys) == len(result.rows) and all(None not in key for key in keys)
    assert result.final_state == SystemsManagerResumeConfig(completed=True)


def test_fan_out_resumes_inside_nested_parent_without_rereading_done_children(
    config: AwsSystemsManagerSourceConfig,
) -> None:
    a1 = _key({"AssociationId": "a-1"})
    e1 = _key({"AssociationId": "a-1", "ExecutionId": "e-1"})
    target = {"AssociationId": "a-1", "ResourceId": "i-a", "ResourceType": "ManagedInstance"}
    result = driver(config).run(
        "association_execution_targets",
        [
            ScriptedResponse(
                json={
                    "Associations": [{"AssociationId": "a-0"}, {"AssociationId": "a-1"}],
                    "NextToken": "associations-2",
                }
            ),
            ScriptedResponse(
                json={
                    "AssociationExecutions": [
                        {"AssociationId": "a-1", "ExecutionId": "e-0"},
                        {"AssociationId": "a-1", "ExecutionId": "e-1"},
                        {"AssociationId": "a-1", "ExecutionId": "e-2"},
                    ],
                }
            ),
            ScriptedResponse(json={"AssociationExecutionTargets": [{**target, "ExecutionId": "e-1"}]}),
            ScriptedResponse(json={"AssociationExecutionTargets": [{**target, "ExecutionId": "e-2"}]}),
            ScriptedResponse(json={"Associations": []}),
        ],
        resume_state=SystemsManagerResumeConfig(parents=((None, a1), ("executions-2", e1)), next_token="targets-2"),
    )
    assert result.raised is None
    assert [request.json() for request in result.requests] == [
        {"MaxResults": 50},
        {"MaxResults": 50, "AssociationId": "a-1", "NextToken": "executions-2"},
        {"MaxResults": 50, "AssociationId": "a-1", "ExecutionId": "e-1", "NextToken": "targets-2"},
        {"MaxResults": 50, "AssociationId": "a-1", "ExecutionId": "e-2"},
        {"MaxResults": 50, "NextToken": "associations-2"},
    ]
    assert [row["execution_id"] for row in result.rows] == ["e-1", "e-2"]
    assert result.final_state == SystemsManagerResumeConfig(completed=True)


@pytest.mark.parametrize("resumed", [False, True])
def test_sessions_read_ended_then_active_sessions(config: AwsSystemsManagerSourceConfig, resumed: bool) -> None:
    active = _key({"MaxResults": 200, "State": "Active"})
    history = [
        ScriptedResponse(json={"Sessions": [{"SessionId": "s-ended", "EndDate": 1735689600}], "NextToken": "h-2"}),
        ScriptedResponse(json={"Sessions": []}),
    ]
    result = driver(config).run(
        "sessions",
        [
            *([] if resumed else history),
            ScriptedResponse(json={"Sessions": [{"SessionId": "s-open", "Status": "Connected"}]}),
        ],
        resume_state=SystemsManagerResumeConfig(parents=((None, active),), next_token="a-2") if resumed else None,
    )
    assert result.raised is None
    expected_requests = [
        *(
            []
            if resumed
            else [{"MaxResults": 200, "State": "History"}, {"MaxResults": 200, "State": "History", "NextToken": "h-2"}]
        ),
        {"MaxResults": 200, "State": "Active", **({"NextToken": "a-2"} if resumed else {})},
    ]
    assert [request.json() for request in result.requests] == expected_requests
    assert [row["session_id"] for row in result.rows] == ([] if resumed else ["s-ended"]) + ["s-open"]
    if not resumed:
        assert result.rows[0]["end_date"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    assert result.final_state == SystemsManagerResumeConfig(completed=True)


_PLACEHOLDER_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.mark.parametrize(
    "schema,script,expected_requests,expected",
    [
        (
            "association_execution_targets",
            [
                ScriptedResponse(json={"Associations": [{"AssociationId": "a-1"}]}),
                ScriptedResponse(json={"AssociationExecutions": [{"AssociationId": "a-1", "ExecutionId": "e-1"}]}),
                ScriptedResponse(json={}),
            ],
            [
                ("ListAssociations", {"MaxResults": 1}),
                ("DescribeAssociationExecutions", {"MaxResults": 1, "AssociationId": "a-1"}),
                (
                    "DescribeAssociationExecutionTargets",
                    {"MaxResults": 1, "AssociationId": "a-1", "ExecutionId": "e-1"},
                ),
            ],
            (True, None),
        ),
        (
            "association_execution_targets",
            [ScriptedResponse(json={}), _error("AssociationDoesNotExist"), _error("AssociationDoesNotExist")],
            [
                ("ListAssociations", {"MaxResults": 1}),
                ("DescribeAssociationExecutions", {"MaxResults": 1, "AssociationId": _PLACEHOLDER_UUID}),
                (
                    "DescribeAssociationExecutionTargets",
                    {"MaxResults": 1, "AssociationId": _PLACEHOLDER_UUID, "ExecutionId": _PLACEHOLDER_UUID},
                ),
            ],
            (True, None),
        ),
        (
            "inventory_entries",
            [ScriptedResponse(json={}), _error("AccessDeniedException")],
            [
                ("GetInventory", {"MaxResults": 1, "ResultAttributes": [{"TypeName": "AWS:InstanceInformation"}]}),
                ("GetInventorySchema", {"MaxResults": 50}),
            ],
            (False, "Grant ssm:GetInventorySchema to read this table."),
        ),
        (
            "compliance_items",
            [
                ScriptedResponse(
                    json={
                        "ResourceComplianceSummaryItems": [
                            {"ResourceId": "i-a", "ResourceType": "ManagedInstance", "ComplianceType": "Association"}
                        ]
                    }
                ),
                _error("AccessDeniedException"),
            ],
            [
                ("ListResourceComplianceSummaries", {"MaxResults": 1}),
                (
                    "ListComplianceItems",
                    {
                        "MaxResults": 1,
                        "ResourceIds": ["i-a"],
                        "ResourceTypes": ["ManagedInstance"],
                        "Filters": [{"Key": "ComplianceType", "Values": ["Association"], "Type": "EQUAL"}],
                    },
                ),
            ],
            (False, "Grant ssm:ListComplianceItems to read this table."),
        ),
    ],
)
def test_fan_out_validation_probes_real_parents_before_placeholders(
    config: AwsSystemsManagerSourceConfig,
    schema: str,
    script: list[ScriptedResponse],
    expected_requests: list[tuple[str, dict[str, Any]]],
    expected: tuple[bool, str | None],
) -> None:
    with scripted_network(script) as network:
        assert validate_credentials(config, API_VERSION, schema) == expected
    assert [
        (request.headers["x-amz-target"].removeprefix("AmazonSSM."), request.json()) for request in network.requests_log
    ] == expected_requests
