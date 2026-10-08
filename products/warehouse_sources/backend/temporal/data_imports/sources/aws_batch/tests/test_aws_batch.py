import json
import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_batch import (
    aws_batch as transport,
    source as source_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_batch.aws_batch import (
    AwsBatchClient,
    AwsBatchError,
    AwsBatchResumeConfig,
    AwsBatchThrottleError,
    aws_batch_source,
    error_for_response,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_batch.settings import BATCH_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_batch.source import AwsBatchSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsbatch import (
    AwsBatchSourceConfig,
)


@pytest.fixture
def config() -> AwsBatchSourceConfig:
    return AwsBatchSourceConfig(
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="example-secret",
        aws_session_token="example-session",
        region="eu-west-1",
    )


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


@pytest.fixture
def session() -> Iterator[MagicMock]:
    with patch.object(transport, "make_tracked_session") as factory:
        yield factory.return_value


def response(payload: Any, status: int = 200, headers: dict[str, str] | None = None) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    result.headers.update(headers or {})
    return result


def test_source_adapter_delegates_validation_and_manager_creation(config: AwsBatchSourceConfig) -> None:
    source = AwsBatchSource()
    inputs = MagicMock(spec=SourceInputs)
    manager = MagicMock(spec=ResumableSourceManager)
    with (
        patch.object(source_module, "validate_credentials", return_value=(True, None)) as validate,
        patch.object(source_module, "ResumableSourceManager", return_value=manager) as manager_factory,
    ):
        assert source.validate_credentials(config, team_id=1, schema_name="jobs") == (True, None)
        assert source.get_resumable_source_manager(inputs) is manager
    validate.assert_called_once_with(config, "jobs", BATCH_API_VERSION)
    manager_factory.assert_called_once_with(inputs, AwsBatchResumeConfig)


@pytest.mark.parametrize(
    "operation,path",
    [
        ("ListJobs", "/v1/listjobs"),
        ("DescribeJobs", "/v1/describejobs"),
        ("DescribeJobQueues", "/v1/describejobqueues"),
        ("DescribeComputeEnvironments", "/v1/describecomputeenvironments"),
        ("DescribeJobDefinitions", "/v1/describejobdefinitions"),
    ],
)
def test_signed_rest_json_request(config: AwsBatchSourceConfig, session: MagicMock, operation: str, path: str) -> None:
    session.post.return_value = response({"nextToken": "next"})
    client = AwsBatchClient(config)
    assert client.request(operation, {"maxResults": 100}) == {"nextToken": "next"}
    args, kwargs = session.post.call_args
    assert args == (f"https://batch.eu-west-1.amazonaws.com{path}",)
    assert json.loads(kwargs["data"]) == {"maxResults": 100}
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["headers"]["X-Amz-Security-Token"] == "example-session"
    assert "/eu-west-1/batch/aws4_request" in kwargs["headers"]["Authorization"]
    assert "X-Amz-Date" in kwargs["headers"]
    assert "X-Amz-Target" not in kwargs["headers"]
    assert client.model.api_version == "2016-08-10"
    assert kwargs["timeout"] == 60
    factory = cast(MagicMock, transport.make_tracked_session)
    assert set(factory.call_args.kwargs["redact_values"]) == {"AKIAEXAMPLE", "example-secret", "example-session"}


@pytest.mark.parametrize("region,suffix", [("cn-north-1", "amazonaws.com.cn"), ("us-gov-west-1", "amazonaws.com")])
def test_region_selects_endpoint_and_signature(
    config: AwsBatchSourceConfig, session: MagicMock, region: str, suffix: str
) -> None:
    config.region = region
    config.aws_session_token = None
    session.post.return_value = response({})
    AwsBatchClient(config).request("DescribeJobQueues", {"maxResults": 1})
    args, kwargs = session.post.call_args
    assert args[0] == f"https://batch.{region}.{suffix}/v1/describejobqueues"
    assert f"/{region}/batch/aws4_request" in kwargs["headers"]["Authorization"]
    assert "X-Amz-Security-Token" not in kwargs["headers"]


@pytest.mark.parametrize("region", ["", "https://example.com", "us-east-1.example.com/", "us-east-1@localhost"])
def test_invalid_region_never_sends_credentials(config: AwsBatchSourceConfig, session: MagicMock, region: str) -> None:
    config.region = region
    valid, reason = validate_credentials(config)
    assert not valid
    assert reason == "Enter an AWS region, such as us-east-1."
    session.post.assert_not_called()


@pytest.mark.parametrize(
    "endpoint,result_key,arn_key",
    [
        ("job_queues", "jobQueues", "jobQueueArn"),
        ("compute_environments", "computeEnvironments", "computeEnvironmentArn"),
        ("job_definitions", "jobDefinitions", "jobDefinitionArn"),
    ],
)
@pytest.mark.parametrize("terminal_token", [None, ""])
def test_full_refresh_pages_through_empty_results_and_checkpoints_terminal_page(
    config: AwsBatchSourceConfig,
    session: MagicMock,
    manager: MagicMock,
    endpoint: str,
    result_key: str,
    arn_key: str,
    terminal_token: str | None,
) -> None:
    session.post.side_effect = [
        response({result_key: [{arn_key: "arn:first"}], "nextToken": "one"}),
        response({result_key: [], "nextToken": "two"}),
        response({result_key: [{arn_key: "arn:last"}], "nextToken": terminal_token}),
    ]
    inputs = MagicMock(spec=SourceInputs)
    inputs.schema_name = endpoint
    inputs.api_version = None
    inputs.should_use_incremental_field = False
    inputs.db_incremental_field_last_value = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    result = AwsBatchSource().source_for_pipeline(config, manager, inputs)
    rows = [row for batch in cast(Iterable[list[dict[str, Any]]], result.items()) for row in batch]
    assert result.primary_keys is not None
    assert [row[result.primary_keys[0]] for row in rows] == ["arn:first", "arn:last"]
    assert all(row["region"] == "eu-west-1" for row in rows)
    assert [json.loads(call.kwargs["data"]) for call in session.post.call_args_list] == [
        {"maxResults": 100},
        {"maxResults": 100, "nextToken": "one"},
        {"maxResults": 100, "nextToken": "two"},
    ]
    assert manager.save_state.call_args.args[0].complete
    assert manager.safe_point.call_count == 3
    manager.clear_state.assert_not_called()
    assert result.on_complete is not None
    result.on_complete()
    manager.clear_state.assert_called_once()
    session.close.assert_called_once()


def test_jobs_discover_queues_and_hydrate_all_statuses(
    config: AwsBatchSourceConfig, session: MagicMock, manager: MagicMock
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(url: str, **kwargs: Any) -> requests.Response:
        payload = json.loads(kwargs["data"])
        calls.append((url.rsplit("/", 1)[-1], payload))
        if url.endswith("describejobqueues"):
            if "nextToken" not in payload:
                return response({"jobQueues": [], "nextToken": "queues-next"})
            return response({"jobQueues": [{"jobQueueArn": "arn:queue:one"}, {"jobQueueArn": "arn:queue:two"}]})
        if url.endswith("listjobs"):
            assert payload["filters"] == [{"name": "JOB_NAME", "values": ["*"]}]
            assert "jobStatus" not in payload
            assert payload["maxResults"] == 100
            if payload["jobQueue"] == "arn:queue:one" and "nextToken" not in payload:
                return response({"jobSummaryList": [], "nextToken": "jobs-next"})
            return response({"jobSummaryList": [{"jobId": payload["jobQueue"] + ":job"}]})
        return response(
            {
                "jobs": [
                    {
                        "jobArn": payload["jobs"][0],
                        "status": "SUCCEEDED",
                        "createdAt": 1735689600000,
                        "startedAt": 0,
                        "stoppedAt": 1735689605000,
                        "attempts": [{"container": {"exitCode": 0}}],
                    }
                ]
            }
        )

    session.post.side_effect = send
    result = aws_batch_source(config, "jobs", manager)
    rows = [row for batch in cast(Iterable[list[dict[str, Any]]], result.items()) for row in batch]
    assert [row["job_arn"] for row in rows] == ["arn:queue:one:job", "arn:queue:two:job"]
    assert rows[0]["created_at"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    assert rows[0]["started_at"] is None
    assert rows[0]["stopped_at"] == dt.datetime(2025, 1, 1, 0, 0, 5, tzinfo=dt.UTC)
    assert rows[0]["attempts"] == [{"container": {"exitCode": 0}}]
    assert [payload.get("nextToken") for operation, payload in calls if operation == "listjobs"] == [
        None,
        "jobs-next",
        None,
    ]
    assert manager.save_state.call_args.args[0].complete
    assert result.sort_mode is None


@pytest.mark.parametrize("job_count", [0, 100, 101])
def test_job_descriptions_respect_batch_limit(
    config: AwsBatchSourceConfig, session: MagicMock, manager: MagicMock, job_count: int
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = AwsBatchResumeConfig(queue_arns=["arn:queue"])
    session.post.side_effect = [
        response({"jobSummaryList": [{"jobId": f"job-{i}"} for i in range(job_count)]}),
        *[response({"jobs": []}) for _ in range(0, job_count, 100)],
    ]
    assert list(cast(Iterable[Any], aws_batch_source(config, "jobs", manager).items())) == []
    described = [json.loads(call.kwargs["data"])["jobs"] for call in session.post.call_args_list[1:]]
    assert all(0 < len(ids) <= 100 for ids in described)
    assert [job for ids in described for job in ids] == [f"job-{i}" for i in range(job_count)]


@pytest.mark.parametrize("endpoint", ["job_queues", "jobs"])
def test_resume_continues_the_saved_page_and_parent(
    config: AwsBatchSourceConfig, session: MagicMock, manager: MagicMock, endpoint: str
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = AwsBatchResumeConfig(
        next_token="saved-page", queue_arns=["arn:completed", "arn:remaining"], queue_index=1
    )
    session.post.return_value = response({"jobQueues": [], "jobSummaryList": []})
    assert list(cast(Iterable[Any], aws_batch_source(config, endpoint, manager).items())) == []
    assert session.post.call_count == 1
    payload = json.loads(session.post.call_args.kwargs["data"])
    assert payload["nextToken"] == "saved-page"
    if endpoint == "jobs":
        assert payload["jobQueue"] == "arn:remaining"
    assert manager.save_state.call_args.args[0].complete


@pytest.mark.parametrize("complete", [False, True])
def test_empty_queue_catalog_and_completed_resume(
    config: AwsBatchSourceConfig, session: MagicMock, manager: MagicMock, complete: bool
) -> None:
    manager.can_resume.return_value = complete
    manager.load_state.return_value = AwsBatchResumeConfig(complete=True)
    session.post.return_value = response({"jobQueues": []})
    assert list(cast(Iterable[Any], aws_batch_source(config, "jobs", manager).items())) == []
    assert session.post.call_count == (0 if complete else 1)


def test_failed_hydration_does_not_checkpoint_missing_rows(
    config: AwsBatchSourceConfig, session: MagicMock, manager: MagicMock
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = AwsBatchResumeConfig(queue_arns=["arn:queue"])
    session.post.side_effect = [
        response({"jobSummaryList": [{"jobId": "job-one"}], "nextToken": "unsafe"}),
        response({"message": "AccessDeniedException"}, 403, {"x-amzn-ErrorType": "AccessDeniedException"}),
    ]
    with pytest.raises(AwsBatchError):
        list(cast(Iterable[Any], aws_batch_source(config, "jobs", manager).items()))
    manager.save_state.assert_not_called()
    session.close.assert_called_once()


@pytest.mark.parametrize("token", ["same", 123])
def test_invalid_page_token_fails_without_checkpoint(
    config: AwsBatchSourceConfig, session: MagicMock, manager: MagicMock, token: str | int
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = AwsBatchResumeConfig(next_token="same")
    session.post.return_value = response({"jobQueues": [], "nextToken": token})
    with pytest.raises(ValueError, match="page token"):
        list(cast(Iterable[Any], aws_batch_source(config, "job_queues", manager).items()))
    manager.save_state.assert_not_called()


@pytest.mark.parametrize(
    "status,payload,headers,code,retryable",
    [
        (400, {"__type": "com.amazonaws.batch#ThrottlingException"}, {}, "ThrottlingException", True),
        (429, {"code": "ThrottlingException"}, {}, "ThrottlingException", False),
        (500, {"message": "Unavailable"}, {}, "HTTP 500", False),
        (
            403,
            {"Message": "Denied"},
            {"x-amzn-ErrorType": "AccessDeniedException:detail"},
            "AccessDeniedException",
            False,
        ),
        (400, {"code": "ClientException", "message": "Invalid input"}, {}, "ClientException", False),
        (502, ["Unexpected response"], {}, "HTTP 502", False),
    ],
)
def test_error_parsing_and_disjoint_retry_policies(
    status: int, payload: Any, headers: dict[str, str], code: str, retryable: bool
) -> None:
    error = error_for_response(response(payload, status, headers))
    assert error.code == code
    assert isinstance(error, AwsBatchThrottleError) == retryable
    if status in (429, 500, 502):
        assert transport.TRANSPORT_RETRY.is_retry("POST", status)


def test_body_throttle_retries_and_non_json_errors(config: AwsBatchSourceConfig, session: MagicMock) -> None:
    session.post.side_effect = [response({"code": "ThrottlingException"}, 400), response({"jobQueues": []})]
    with patch.object(cast(Any, AwsBatchClient.request).retry, "wait", wait_none()):
        assert AwsBatchClient(config).request("DescribeJobQueues", {"maxResults": 1}) == {"jobQueues": []}
    assert session.post.call_count == 2
    invalid = response({}, 503)
    invalid._content = b"temporarily unavailable"
    assert error_for_response(invalid).message == "temporarily unavailable"


@pytest.mark.parametrize("schema_name", [None, "jobs", "job_queues", "compute_environments", "job_definitions"])
@pytest.mark.parametrize(
    "code,message,reason_fragment,allow_create",
    [
        ("AccessDeniedException", "Access denied", "Grant batch:", True),
        ("ClientException", "User is not authorized to perform: batch:DescribeJobQueues", "Grant batch:", True),
        (
            "UnrecognizedClientException",
            "The security token included in the request is invalid.",
            "rejected the credentials",
            False,
        ),
        (
            "InvalidSignatureException",
            "The request signature we calculated does not match the signature you provided.",
            "rejected the credentials",
            False,
        ),
        ("ExpiredTokenException", "The security token included in the request is expired", "expired", False),
        ("SubscriptionRequiredException", "Subscription required", "Enable AWS Batch", False),
        ("OptInRequired", "Service not enabled", "selected region", False),
        ("ClientException", "Invalid parameter", "Check the region", False),
    ],
)
def test_credential_error_mapping(
    config: AwsBatchSourceConfig,
    session: MagicMock,
    schema_name: str | None,
    code: str,
    message: str,
    reason_fragment: str,
    allow_create: bool,
) -> None:
    session.post.return_value = response({"__type": code, "message": message}, 400)
    valid, reason = validate_credentials(config, schema_name)
    assert valid == (allow_create and schema_name is None)
    if valid:
        assert reason is None
    else:
        assert reason is not None and reason_fragment in reason
    session.close.assert_called_once()


@pytest.mark.parametrize("exception", [requests.Timeout(), requests.ConnectionError()])
def test_connection_error_is_actionable(config: AwsBatchSourceConfig, session: MagicMock, exception: Exception) -> None:
    session.post.side_effect = exception
    assert validate_credentials(config) == (False, "Could not reach AWS Batch. Check the region and try again.")


@pytest.mark.parametrize("schema_name", [None, "job_queues", "compute_environments", "job_definitions", "jobs"])
def test_validation_probes_only_required_operations(
    config: AwsBatchSourceConfig, session: MagicMock, schema_name: str | None
) -> None:
    session.post.side_effect = [
        response({"jobQueues": [{"jobQueueArn": "arn:queue"}]}),
        response({"jobSummaryList": [{"jobId": "job-one"}]}),
        response({"jobs": []}),
    ]
    assert validate_credentials(config, schema_name) == (True, None)
    assert session.post.call_count == (3 if schema_name == "jobs" else 1)
    assert json.loads(session.post.call_args_list[0].kwargs["data"]) == {"maxResults": 1}
    if schema_name == "jobs":
        assert json.loads(session.post.call_args_list[-1].kwargs["data"]) == {"jobs": ["job-one"]}


@pytest.mark.parametrize("field", ["aws_access_key_id", "aws_secret_access_key"])
def test_missing_credentials_do_not_call_aws(config: AwsBatchSourceConfig, session: MagicMock, field: str) -> None:
    setattr(config, field, "")
    assert validate_credentials(config) == (False, "Enter both an AWS access key ID and a secret access key.")
    session.post.assert_not_called()


def test_unknown_endpoint_and_version_fail_before_request(
    config: AwsBatchSourceConfig, session: MagicMock, manager: MagicMock
) -> None:
    with pytest.raises(ValueError, match="Unknown AWS Batch table"):
        aws_batch_source(config, "unknown", manager)
    assert validate_credentials(config, "unknown") == (False, "Unknown AWS Batch table: unknown")
    with pytest.raises(ValueError, match="Unsupported AWS Batch API version"):
        AwsBatchClient(config, api_version="1900-01-01")
    session.post.assert_not_called()


def test_invalid_success_body_is_not_silently_empty(config: AwsBatchSourceConfig, session: MagicMock) -> None:
    session.post.return_value = response([])
    with pytest.raises(ValueError, match="invalid response"):
        AwsBatchClient(config, BATCH_API_VERSION).request("DescribeJobQueues", {"maxResults": 1})
