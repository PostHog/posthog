import json
import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
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


def driver(config: AwsBatchSourceConfig) -> SourceDriver:
    return SourceDriver(AwsBatchSource(), config)


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
def test_signed_rest_json_request(config: AwsBatchSourceConfig, operation: str, path: str) -> None:
    with scripted_network([ScriptedResponse(json={"nextToken": "next"})]) as network:
        client = AwsBatchClient(config)
        assert client.request(operation, {"maxResults": 100}) == {"nextToken": "next"}
        client.close()
    request = network.requests_log[0]
    assert request.url == f"https://batch.eu-west-1.amazonaws.com{path}"
    assert request.json() == {"maxResults": 100}
    assert request.headers["content-type"] == "application/json"
    assert request.headers["x-amz-security-token"] == "example-session"
    assert "/eu-west-1/batch/aws4_request" in request.headers["authorization"]
    assert "x-amz-date" in request.headers
    assert "x-amz-target" not in request.headers
    assert client.model.api_version == "2016-08-10"
    assert request.read_timeout == 60
    assert set(network.session_options[0]["redact_values"]) == {"AKIAEXAMPLE", "example-secret", "example-session"}


@pytest.mark.parametrize("region,suffix", [("cn-north-1", "amazonaws.com.cn"), ("us-gov-west-1", "amazonaws.com")])
def test_region_selects_endpoint_and_signature(config: AwsBatchSourceConfig, region: str, suffix: str) -> None:
    config.region = region
    config.aws_session_token = None
    with scripted_network([ScriptedResponse(json={})]) as network:
        client = AwsBatchClient(config)
        client.request("DescribeJobQueues", {"maxResults": 1})
        client.close()
    request = network.requests_log[0]
    assert request.url == f"https://batch.{region}.{suffix}/v1/describejobqueues"
    assert f"/{region}/batch/aws4_request" in request.headers["authorization"]
    assert "x-amz-security-token" not in request.headers


@pytest.mark.parametrize("region", ["", "https://example.com", "us-east-1.example.com/", "us-east-1@localhost"])
def test_invalid_region_never_sends_credentials(config: AwsBatchSourceConfig, region: str) -> None:
    config.region = region
    with scripted_network([]) as network:
        valid, reason = validate_credentials(config)
    assert not valid
    assert reason == "Enter an AWS region, such as us-east-1."
    assert network.requests_log == []


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


def test_jobs_discover_queues_and_hydrate_all_statuses(config: AwsBatchSourceConfig) -> None:
    def send(request: RecordedRequest) -> ScriptedResponse:
        payload = request.json()
        if request.path.endswith("describejobqueues"):
            if "nextToken" not in payload:
                return ScriptedResponse(json={"jobQueues": [], "nextToken": "queues-next"})
            return ScriptedResponse(
                json={"jobQueues": [{"jobQueueArn": "arn:queue:one"}, {"jobQueueArn": "arn:queue:two"}]}
            )
        if request.path.endswith("listjobs"):
            assert payload["filters"] == [{"name": "JOB_NAME", "values": ["*"]}]
            assert "jobStatus" not in payload
            assert payload["maxResults"] == 100
            if payload["jobQueue"] == "arn:queue:one" and "nextToken" not in payload:
                return ScriptedResponse(json={"jobSummaryList": [], "nextToken": "jobs-next"})
            return ScriptedResponse(json={"jobSummaryList": [{"jobId": payload["jobQueue"] + ":job"}]})
        return ScriptedResponse(
            json={
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

    result = driver(config).run("jobs", send)
    assert result.raised is None
    rows = result.rows
    assert [row["job_arn"] for row in rows] == ["arn:queue:one:job", "arn:queue:two:job"]
    assert rows[0]["created_at"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    assert rows[0]["started_at"] is None
    assert rows[0]["stopped_at"] == dt.datetime(2025, 1, 1, 0, 0, 5, tzinfo=dt.UTC)
    assert rows[0]["attempts"] == [{"container": {"exitCode": 0}}]
    assert [request.json().get("nextToken") for request in result.requests if request.path.endswith("listjobs")] == [
        None,
        "jobs-next",
        None,
    ]
    assert result.saved_states[-1].complete
    assert result.response is not None and result.response.sort_mode is None


def test_job_children_describe_array_children_and_nodes(config: AwsBatchSourceConfig) -> None:
    def send(request: RecordedRequest) -> ScriptedResponse:
        payload = request.json()
        if request.path.endswith("describejobqueues"):
            return ScriptedResponse(
                json={
                    "jobQueues": [
                        {"jobQueueArn": "arn:queue:ecs", "computeEnvironmentOrder": [{"order": 1}]},
                        {"jobQueueArn": "arn:queue:service", "serviceEnvironmentOrder": [{"order": 1}]},
                    ]
                }
            )
        if request.path.endswith("listjobs"):
            assert payload["jobQueue"] == "arn:queue:ecs"
            assert payload["filters"] == [{"name": "JOB_NAME", "values": ["*"]}]
            if "nextToken" not in payload:
                return ScriptedResponse(
                    json={
                        "jobSummaryList": [{"jobId": "plain"}, {"jobId": "array", "arrayProperties": {"size": 101}}],
                        "nextToken": "page-two",
                    }
                )
            return ScriptedResponse(json={"jobSummaryList": [{"jobId": "mnp", "nodeProperties": {"numNodes": 2}}]})
        return ScriptedResponse(
            json={"jobs": [{"jobArn": f"arn:job/{job_id}", "createdAt": 1735689600000} for job_id in payload["jobs"]]}
        )

    result = driver(config).run("job_children", send)
    assert result.raised is None
    described = [request.json()["jobs"] for request in result.requests if request.path.endswith("describejobs")]
    assert described == [[f"array:{i}" for i in range(100)], ["array:100"], ["mnp#0", "mnp#1"]]
    rows = result.rows
    assert len(rows) == 103
    assert {row["parent_job_id"] for row in rows} == {"array", "mnp"}
    assert rows[-1] == {
        "job_arn": "arn:job/mnp#1",
        "created_at": dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
        "region": "eu-west-1",
        "parent_job_id": "mnp",
    }
    assert result.saved_states[-1].complete


def test_job_children_resume_mid_parent_and_finish_queue(config: AwsBatchSourceConfig) -> None:
    result = driver(config).run(
        "job_children",
        [ScriptedResponse(json={"jobs": []}), ScriptedResponse(json={"jobSummaryList": []})],
        resume_state=AwsBatchResumeConfig(
            queue_arns=["arn:queue"],
            next_token="page-two",
            child_prefixes=["done:", "array:"],
            child_counts=[5, 150],
            parent_index=1,
            child_offset=100,
        ),
    )
    assert result.raised is None
    assert result.requests[0].json() == {"jobs": [f"array:{i}" for i in range(100, 150)]}
    assert result.requests[1].json()["nextToken"] == "page-two"
    assert len(result.requests) == 2
    assert result.saved_states[-1].complete


def test_service_jobs_read_only_service_queues(config: AwsBatchSourceConfig) -> None:
    def send(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("describejobqueues"):
            return ScriptedResponse(
                json={
                    "jobQueues": [
                        {"jobQueueArn": "arn:queue:ecs", "computeEnvironmentOrder": [{"order": 1}]},
                        {"jobQueueArn": "arn:queue:service", "serviceEnvironmentOrder": [{"order": 1}]},
                    ]
                }
            )
        payload = request.json()
        assert payload["jobQueue"] == "arn:queue:service"
        assert payload["filters"] == [{"name": "JOB_NAME", "values": ["*"]}]
        return ScriptedResponse(
            json={"jobSummaryList": [{"jobArn": "arn:service-job", "status": "FAILED", "stoppedAt": 1735689600000}]}
        )

    result = driver(config).run("service_jobs", send)
    assert result.raised is None
    assert [request.path for request in result.requests] == ["/v1/describejobqueues", "/v1/listservicejobs"]
    assert result.rows == [
        {
            "job_arn": "arn:service-job",
            "status": "FAILED",
            "stopped_at": dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
            "region": "eu-west-1",
            "job_queue": "arn:queue:service",
        }
    ]
    assert result.saved_states[-1].complete


@pytest.mark.parametrize(
    "endpoint,list_key,item_key,detail_path,expected_details",
    [
        (
            "scheduling_policies",
            "schedulingPolicies",
            "arn",
            "/v1/describeschedulingpolicies",
            [{"arns": ["arn:one"]}, {"arns": ["arn:two", "arn:three"]}],
        ),
        (
            "consumable_resources",
            "consumableResources",
            "consumableResourceArn",
            "/v1/describeconsumableresource",
            [{"consumableResource": arn} for arn in ("arn:one", "arn:two", "arn:three")],
        ),
    ],
)
def test_listed_resources_are_described_page_by_page(
    config: AwsBatchSourceConfig,
    endpoint: str,
    list_key: str,
    item_key: str,
    detail_path: str,
    expected_details: list[dict[str, Any]],
) -> None:
    def send(request: RecordedRequest) -> ScriptedResponse:
        payload = request.json()
        if request.path == detail_path:
            if endpoint == "scheduling_policies":
                return ScriptedResponse(
                    json={"schedulingPolicies": [{"arn": arn, "fairsharePolicy": {}} for arn in payload["arns"]]}
                )
            return ScriptedResponse(
                json={"consumableResourceArn": payload["consumableResource"], "availableQuantity": 3, "createdAt": 0}
            )
        if "nextToken" not in payload:
            return ScriptedResponse(json={list_key: [{item_key: "arn:one"}], "nextToken": "next"})
        return ScriptedResponse(json={list_key: [{item_key: "arn:two"}, {item_key: "arn:three"}]})

    result = driver(config).run(endpoint, send)
    assert result.raised is None
    assert [request.json() for request in result.requests if request.path == detail_path] == expected_details
    rows = result.rows
    assert result.response is not None and result.response.primary_keys is not None
    assert [row[result.response.primary_keys[0]] for row in rows] == ["arn:one", "arn:two", "arn:three"]
    if endpoint == "scheduling_policies":
        assert rows[0]["fairshare_policy"] == {}
    else:
        assert rows[0]["available_quantity"] == 3
        assert rows[0]["created_at"] is None
    assert result.saved_states[-1].complete


@pytest.mark.parametrize("job_count", [0, 100, 101])
def test_job_descriptions_respect_batch_limit(config: AwsBatchSourceConfig, job_count: int) -> None:
    result = driver(config).run(
        "jobs",
        [
            ScriptedResponse(json={"jobSummaryList": [{"jobId": f"job-{i}"} for i in range(job_count)]}),
            *[ScriptedResponse(json={"jobs": []}) for _ in range(0, job_count, 100)],
        ],
        resume_state=AwsBatchResumeConfig(queue_arns=["arn:queue"]),
    )
    assert result.raised is None
    assert result.items == []
    described = [request.json()["jobs"] for request in result.requests[1:]]
    assert all(0 < len(ids) <= 100 for ids in described)
    assert [job for ids in described for job in ids] == [f"job-{i}" for i in range(job_count)]


@pytest.mark.parametrize("endpoint", ["job_queues", "jobs"])
def test_resume_continues_the_saved_page_and_parent(config: AwsBatchSourceConfig, endpoint: str) -> None:
    result = driver(config).run(
        endpoint,
        [ScriptedResponse(json={"jobQueues": [], "jobSummaryList": []})],
        resume_state=AwsBatchResumeConfig(
            next_token="saved-page", queue_arns=["arn:completed", "arn:remaining"], queue_index=1
        ),
    )
    assert result.raised is None
    assert result.items == []
    assert len(result.requests) == 1
    payload = result.requests[0].json()
    assert payload["nextToken"] == "saved-page"
    if endpoint == "jobs":
        assert payload["jobQueue"] == "arn:remaining"
    assert result.saved_states[-1].complete


@pytest.mark.parametrize("complete", [False, True])
def test_empty_queue_catalog_and_completed_resume(config: AwsBatchSourceConfig, complete: bool) -> None:
    result = driver(config).run(
        "jobs",
        [ScriptedResponse(json={"jobQueues": []})],
        resume_state=AwsBatchResumeConfig(complete=True) if complete else None,
    )
    assert result.raised is None
    assert result.items == []
    assert len(result.requests) == (0 if complete else 1)


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
def test_invalid_page_token_fails_without_checkpoint(config: AwsBatchSourceConfig, token: str | int) -> None:
    result = driver(config).run(
        "job_queues",
        [ScriptedResponse(json={"jobQueues": [], "nextToken": token})],
        resume_state=AwsBatchResumeConfig(next_token="same"),
    )
    assert isinstance(result.raised, ValueError)
    assert "page token" in str(result.raised)
    assert result.saved_states == []
    assert result.final_state == AwsBatchResumeConfig(next_token="same")


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


def test_body_throttle_retries_and_non_json_errors(config: AwsBatchSourceConfig) -> None:
    with scripted_network(
        [ScriptedResponse(status=400, json={"code": "ThrottlingException"}), ScriptedResponse(json={"jobQueues": []})]
    ) as network:
        client = AwsBatchClient(config)
        assert client.request("DescribeJobQueues", {"maxResults": 1}) == {"jobQueues": []}
        client.close()
    assert len(network.requests_log) == 2
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


@pytest.mark.parametrize("exception", [requests.Timeout()])
def test_connection_error_is_actionable(config: AwsBatchSourceConfig, exception: Exception) -> None:
    with scripted_network(always(exception)) as network:
        assert validate_credentials(config) == (False, "Could not reach AWS Batch. Check the region and try again.")
    assert {request.path for request in network.requests_log} == {"/v1/describejobqueues"}


@pytest.mark.parametrize(
    "schema_name,paths",
    [
        (None, ["describejobqueues"]),
        ("job_queues", ["describejobqueues"]),
        ("compute_environments", ["describecomputeenvironments"]),
        ("job_definitions", ["describejobdefinitions"]),
        ("jobs", ["describejobqueues", "listjobs", "describejobs"]),
        ("job_children", ["describejobqueues", "describejobqueues", "listjobs", "describejobs"]),
        ("service_jobs", ["describejobqueues", "listservicejobs"]),
        ("scheduling_policies", ["listschedulingpolicies", "describeschedulingpolicies"]),
        ("consumable_resources", ["listconsumableresources", "describeconsumableresource"]),
    ],
)
def test_validation_probes_only_required_operations(
    config: AwsBatchSourceConfig, schema_name: str | None, paths: list[str]
) -> None:
    def send(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("describejobqueues"):
            if "nextToken" not in request.json():
                return ScriptedResponse(
                    json={
                        "jobQueues": [{"jobQueueArn": "arn:service-queue", "serviceEnvironmentOrder": [{"order": 1}]}],
                        "nextToken": "queues-next",
                    }
                )
            return ScriptedResponse(
                json={"jobQueues": [{"jobQueueArn": "arn:queue", "computeEnvironmentOrder": [{"order": 1}]}]}
            )
        return ScriptedResponse(
            json={
                "jobSummaryList": [{"jobId": "job-one"}],
                "jobs": [],
                "schedulingPolicies": [{"arn": "arn:policy"}],
                "consumableResources": [{"consumableResourceArn": "arn:resource"}],
            }
        )

    with scripted_network(send) as network:
        assert validate_credentials(config, schema_name) == (True, None)
    assert [request.path.removeprefix("/v1/") for request in network.requests_log] == paths
    probed_queues = {"job_children": "arn:queue", "service_jobs": "arn:service-queue"}
    if schema_name in probed_queues:
        assert (
            network.requests_log[-1 if schema_name == "service_jobs" else -2].json()["jobQueue"]
            == probed_queues[schema_name]
        )
    if schema_name in ("jobs", "job_children"):
        assert network.requests_log[-1].json() == {"jobs": ["job-one"]}


@pytest.mark.parametrize("field", ["aws_access_key_id", "aws_secret_access_key"])
def test_missing_credentials_do_not_call_aws(config: AwsBatchSourceConfig, field: str) -> None:
    setattr(config, field, "")
    with scripted_network([]) as network:
        assert validate_credentials(config) == (False, "Enter both an AWS access key ID and a secret access key.")
    assert network.requests_log == []


def test_unknown_endpoint_and_version_fail_before_request(config: AwsBatchSourceConfig) -> None:
    result = driver(config).run("unknown", [])
    assert isinstance(result.raised, ValueError)
    assert "Unknown AWS Batch table" in str(result.raised)
    with scripted_network([]) as network:
        assert validate_credentials(config, "unknown") == (False, "Unknown AWS Batch table: unknown")
        with pytest.raises(ValueError, match="Unsupported AWS Batch API version"):
            AwsBatchClient(config, api_version="1900-01-01")
    assert result.requests == []
    assert network.requests_log == []


def test_invalid_success_body_is_not_silently_empty(config: AwsBatchSourceConfig) -> None:
    with scripted_network([ScriptedResponse(json=[])]) as network:
        client = AwsBatchClient(config, BATCH_API_VERSION)
        with pytest.raises(ValueError, match="invalid response"):
            client.request("DescribeJobQueues", {"maxResults": 1})
        client.close()
    assert len(network.requests_log) == 1
