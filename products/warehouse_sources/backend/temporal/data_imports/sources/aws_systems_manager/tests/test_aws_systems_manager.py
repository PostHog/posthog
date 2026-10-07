import json
import datetime as dt
from collections.abc import Generator, Iterable, Iterator
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
import structlog
from tenacity import wait_none

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
    config: AwsSystemsManagerSourceConfig, http: MagicMock, region: str, host: str, token: str | None
) -> None:
    config.aws_region = region
    config.aws_session_token = token
    client = SystemsManagerClient(config, API_VERSION)
    client.request("DescribeInstanceInformation", {"MaxResults": 5})
    call = http.post.call_args
    assert call.args == (f"https://{host}/",)
    assert json.loads(call.kwargs["data"]) == {"MaxResults": 5}
    headers = call.kwargs["headers"]
    assert headers["X-Amz-Target"] == "AmazonSSM.DescribeInstanceInformation"
    assert headers["Content-Type"] == "application/x-amz-json-1.1"
    assert headers.get("X-Amz-Security-Token") == token
    assert f"/{region}/ssm/aws4_request" in headers["Authorization"]
    assert "content-type;host;x-amz-date;" in headers["Authorization"]
    assert "x-amz-target" in headers["Authorization"]
    assert headers["X-Amz-Date"]
    assert call.kwargs["allow_redirects"] is False
    assert call.kwargs["timeout"] == 60
    factory = cast(MagicMock, transport.make_tracked_session)
    assert config.aws_secret_access_key in factory.call_args.kwargs["redact_values"]
    if token:
        assert token in factory.call_args.kwargs["redact_values"]


@pytest.mark.parametrize(
    "region", ["", "https://example.com", "us-east-1.example.com", "../us-east-1", "us-east-1/path"]
)
def test_rejects_region_before_sending_credentials(
    config: AwsSystemsManagerSourceConfig, http: MagicMock, region: str
) -> None:
    config.aws_region = region
    valid, reason = validate_credentials(config, API_VERSION)
    assert not valid and reason and "valid AWS region" in reason
    http.post.assert_not_called()


def test_rejects_unsupported_model_version(config: AwsSystemsManagerSourceConfig, http: MagicMock) -> None:
    valid, reason = validate_credentials(config, "2099-01-01")
    assert not valid and reason and "Unsupported" in reason
    http.post.assert_not_called()


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
    config: AwsSystemsManagerSourceConfig, http: MagicMock, manager: MagicMock
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = SystemsManagerResumeConfig(completed=True)
    assert list(iter_batches(aws_systems_manager_source(config, "associations", API_VERSION, manager))) == []
    http.post.assert_not_called()


@pytest.mark.parametrize("resumed", [False, True])
def test_expired_token_restarts_only_saved_walk(
    config: AwsSystemsManagerSourceConfig, http: MagicMock, manager: MagicMock, resumed: bool
) -> None:
    manager.can_resume.return_value = resumed
    manager.load_state.return_value = SystemsManagerResumeConfig(next_token="expired")
    http.post.side_effect = [
        response({"__type": "InvalidNextToken", "Message": "The specified token isn't valid."}, 400),
        response({"Associations": [{"AssociationId": "a-example"}]}),
    ]
    source = aws_systems_manager_source(config, "associations", API_VERSION, manager)
    if resumed:
        batches = list(iter_batches(source))
        assert batches[0][0]["association_id"] == "a-example"
        assert json.loads(http.post.call_args_list[1].kwargs["data"]) == {"MaxResults": 50}
    else:
        with pytest.raises(SystemsManagerError, match="InvalidNextToken"):
            list(iter_batches(source))
        assert http.post.call_count == 1


@pytest.mark.parametrize("token", ["same", 123])
def test_invalid_pagination_fails_without_loop(
    config: AwsSystemsManagerSourceConfig, http: MagicMock, manager: MagicMock, token: object
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = SystemsManagerResumeConfig(next_token="same")
    http.post.return_value = response({"NextToken": token})
    with pytest.raises(ValueError, match="invalid or repeated page token"):
        list(iter_batches(aws_systems_manager_source(config, "associations", API_VERSION, manager)))
    assert http.post.call_count == 1
    manager.save_state.assert_not_called()


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
    config: AwsSystemsManagerSourceConfig, http: MagicMock, code: str, fragment: str
) -> None:
    http.post.return_value = response({"__type": f"com.amazonaws.ssm#{code}", "message": "Rejected"}, 400)
    valid, reason = validate_credentials(config, API_VERSION)
    assert not valid and reason and fragment in reason
    error = error_for_response(http.post.return_value)
    matches = [
        message
        for pattern, message in AwsSystemsManagerSource().get_non_retryable_errors().items()
        if pattern in str(error)
    ]
    assert reason in matches
    assert http.post.call_count == 1


@pytest.mark.parametrize("code", ["AccessDenied", "AccessDeniedException"])
@pytest.mark.parametrize("schema,expected", [(None, True), ("inventory", False)])
def test_permission_denial_only_allows_source_creation(
    config: AwsSystemsManagerSourceConfig, http: MagicMock, code: str, schema: str | None, expected: bool
) -> None:
    http.post.return_value = response({"__type": code, "Message": "Access denied"}, 400)
    valid, reason = validate_credentials(config, API_VERSION, schema)
    assert valid is expected
    assert reason is None if expected else reason == "Grant ssm:GetInventory to read this table."
    assert http.post.call_count == 1


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
def test_missing_credentials_do_not_send_request(
    config: AwsSystemsManagerSourceConfig, http: MagicMock, field: str
) -> None:
    setattr(config, field, "")
    valid, reason = validate_credentials(config, API_VERSION)
    assert not valid and reason and "Enter both" in reason
    http.post.assert_not_called()


def test_unknown_table_fails_before_request(
    config: AwsSystemsManagerSourceConfig, http: MagicMock, manager: MagicMock
) -> None:
    valid, reason = validate_credentials(config, API_VERSION, "unknown")
    assert not valid and reason and "Unknown" in reason
    with pytest.raises(ValueError, match="Unknown AWS Systems Manager table"):
        aws_systems_manager_source(config, "unknown", API_VERSION, manager)
    http.post.assert_not_called()


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
def test_retries_body_throttling(config: AwsSystemsManagerSourceConfig, http: MagicMock, code: str) -> None:
    http.post.side_effect = [response({"__type": code}, 400), response({"Associations": []})]
    client = SystemsManagerClient(config, API_VERSION)
    request = cast(Any, client.request).retry_with(wait=wait_none())
    assert request(client, "ListAssociations", {"MaxResults": 50}) == {"Associations": []}
    assert http.post.call_count == 2


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_status_retries_belong_only_to_tracked_transport(
    config: AwsSystemsManagerSourceConfig, http: MagicMock, status: int
) -> None:
    http.post.return_value = response({"__type": "InternalServerError"}, status)
    with pytest.raises(SystemsManagerError):
        SystemsManagerClient(config, API_VERSION).request("ListAssociations", {"MaxResults": 50})
    assert http.post.call_count == 1
    factory = cast(MagicMock, transport.make_tracked_session)
    assert factory.call_args.kwargs["retry"].is_retry("POST", status)


def test_network_failure_is_not_reported_as_valid_credentials(
    config: AwsSystemsManagerSourceConfig, http: MagicMock
) -> None:
    http.post.side_effect = requests.ConnectionError("unreachable")
    valid, reason = validate_credentials(config, API_VERSION)
    assert not valid and reason and "Could not reach" in reason
    http.close.assert_called_once()


def test_normalizes_nested_counts_timestamps_and_composite_keys(
    config: AwsSystemsManagerSourceConfig, http: MagicMock, manager: MagicMock
) -> None:
    http.post.return_value = response(
        {
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
    source = aws_systems_manager_source(config, "resource_compliance_summaries", API_VERSION, manager)
    batches = list(iter_batches(source))
    rows = batches[0]
    assert len({tuple(row[key] for key in source.primary_keys or []) for row in rows}) == 2
    assert rows[0]["compliant_summary_compliant_count"] == 2
    assert rows[0]["execution_summary_execution_time"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)


def test_preserves_inventory_content(
    config: AwsSystemsManagerSourceConfig, http: MagicMock, manager: MagicMock
) -> None:
    data = {
        "AWS:InstanceInformation": {
            "CaptureTime": "2025-01-01T00:00:00Z",
            "Content": [{"InstanceId": "i-example", "InstanceStatus": "Stopped"}],
        }
    }
    http.post.return_value = response({"Entities": [{"Id": "i-example", "Data": data}]})
    batches = list(iter_batches(aws_systems_manager_source(config, "inventory", API_VERSION, manager)))
    row = batches[0][0]
    assert json.loads(row["data"]) == data


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
