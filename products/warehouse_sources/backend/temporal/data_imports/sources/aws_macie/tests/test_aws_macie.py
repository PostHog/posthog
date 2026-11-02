import json
import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_macie.aws_macie import (
    AwsMacieClient,
    AwsMacieError,
    AwsMacieResumeConfig,
    aws_macie_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_macie.source import AwsMacieSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsmacie import (
    AwsMacieSourceConfig,
)


class MemoryResumeManager(ResumableSourceManager[AwsMacieResumeConfig]):
    def __init__(self, state: AwsMacieResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[AwsMacieResumeConfig] = []
        self.safe_points = 0

    def load_state(self) -> AwsMacieResumeConfig | None:
        return self.state

    def save_state(self, data: AwsMacieResumeConfig) -> None:
        self.state = data
        self.saved.append(data)

    def clear_state(self) -> None:
        self.state = None

    def safe_point(self) -> None:
        self.safe_points += 1


def response(body: object, status: int = 200, headers: dict[str, str] | None = None) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    result.headers.update(headers or {})
    return result


@pytest.fixture
def config() -> AwsMacieSourceConfig:
    return AwsMacieSourceConfig(
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="example-secret",
        aws_session_token="example-token",
        region="eu-west-1",
    )


@pytest.fixture
def driver(config: AwsMacieSourceConfig) -> SourceDriver:
    return SourceDriver(AwsMacieSource(), config)


@pytest.fixture
def session() -> Iterator[Mock]:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.aws_macie.aws_macie.make_tracked_session"
    ) as factory:
        factory.return_value.request.return_value = response({})
        yield factory.return_value


@pytest.mark.parametrize(
    "operation,payload,method,path",
    [
        ("ListFindings", {"maxResults": 50}, "POST", "/findings"),
        ("GetFindings", {"findingIds": ["finding-1"]}, "POST", "/findings/describe"),
        ("DescribeBuckets", {"maxResults": 50}, "POST", "/datasources/s3"),
        ("ListClassificationJobs", {"maxResults": 50}, "POST", "/jobs/list"),
        ("ListMembers", {"maxResults": 25, "nextToken": "a+b/=", "onlyAssociated": "false"}, "GET", "/members"),
    ],
)
def test_signed_rest_requests(
    config: AwsMacieSourceConfig, operation: str, payload: dict[str, Any], method: str, path: str
) -> None:
    with scripted_network([ScriptedResponse(json={})]) as network:
        client = AwsMacieClient(config)
        client.request(operation, payload)
        client.close()
    request = network.requests_log[0]
    assert request.method == method
    assert request.origin == "https://macie2.eu-west-1.amazonaws.com"
    assert request.path == path
    if method == "POST":
        assert request.json() == payload
        assert request.headers["content-type"] == "application/json"
    else:
        assert request.query == {key: (str(value),) for key, value in payload.items()}
        assert request.body is None
    assert "AWS4-HMAC-SHA256" in request.headers["authorization"]
    assert "/eu-west-1/macie2/aws4_request" in request.headers["authorization"]
    assert request.headers["x-amz-security-token"] == "example-token"
    assert "x-amz-date" in request.headers
    assert "x-amz-target" not in request.headers
    assert request.read_timeout == 60


def test_signed_rest_requests_do_not_follow_redirects(config: AwsMacieSourceConfig) -> None:
    with scripted_network([ScriptedResponse(status=302, headers={"Location": "/redirect"})]) as network:
        client = AwsMacieClient(config)
        with pytest.raises(AwsMacieError, match="HTTP 302"):
            client.request("ListFindings", {"maxResults": 50})
        client.close()
    assert [request.path for request in network.requests_log] == ["/findings"]


@pytest.mark.parametrize("incremental", [False, True])
def test_findings_filter_and_hydration(config: AwsMacieSourceConfig, session: Mock, incremental: bool) -> None:
    session.request.side_effect = [
        response({"findingIds": ["finding-1"], "nextToken": "page-two"}),
        response({"findings": [{"id": "finding-1", "accountId": "111111111111", "updatedAt": "2025-01-02T00:00:00Z"}]}),
        response({"findingIds": ["finding-2"]}),
        response({"findings": [{"id": "finding-2", "accountId": "111111111111", "updatedAt": "2025-01-01T00:00:00Z"}]}),
    ]
    inputs = SourceInputs(
        schema_name="findings",
        schema_id="schema",
        source_id="source",
        team_id=1,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
        db_incremental_field_earliest_value=None,
        incremental_field="updated_at",
        incremental_field_type=None,
        job_id="job",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )
    manager = MemoryResumeManager()
    resource = AwsMacieSource().source_for_pipeline(config, manager, inputs)
    batches = list(cast(Iterable[Any], resource.items()))
    assert [batch[0]["id"] for batch in batches] == ["finding-1", "finding-2"]
    assert batches[0][0]["account_id"] == "111111111111"
    assert batches[0][0]["updated_at"] == dt.datetime(2025, 1, 2, tzinfo=dt.UTC)
    assert batches[0][0]["region"] == "eu-west-1"
    calls = session.request.call_args_list
    for index in (0, 2):
        payload = json.loads(calls[index].kwargs["data"])
        assert payload["sortCriteria"] == {"attributeName": "updatedAt", "orderBy": "ASC"}
        if incremental:
            assert payload["findingCriteria"] == {"criterion": {"updatedAt": {"gte": 1735689600000}}}
        else:
            assert "findingCriteria" not in payload
    assert json.loads(calls[2].kwargs["data"])["nextToken"] == "page-two"
    assert json.loads(calls[1].kwargs["data"])["findingIds"] == ["finding-1"]
    assert resource.sort_mode == "desc"
    assert manager.state is not None and manager.state.completed
    assert resource.on_complete is not None
    resource.on_complete()
    assert manager.load_state() is None
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "endpoint,key,item",
    [
        ("buckets", "buckets", {"bucketArn": "arn:aws:s3:::example-bucket", "bucketCreatedAt": "2025-01-01T00:00:00Z"}),
        ("classification_jobs", "items", {"jobId": "job-1", "createdAt": "2025-01-01T00:00:00Z"}),
        ("members", "members", {"accountId": "111111111111", "updatedAt": "2025-01-01T00:00:00Z"}),
        ("usage_statistics", "records", {"accountId": "111111111111", "freeTrialStartDate": "2025-01-01T00:00:00Z"}),
    ],
)
@pytest.mark.parametrize("terminal_token", [None, ""])
def test_empty_page_continues_to_terminal_page(
    driver: SourceDriver,
    endpoint: str,
    key: str,
    item: dict[str, Any],
    terminal_token: str | None,
) -> None:
    result = driver.run(
        endpoint,
        [
            ScriptedResponse(json={key: [], "nextToken": "page-two"}),
            ScriptedResponse(json={key: [item], "nextToken": terminal_token}),
        ],
    )
    assert result.raised is None
    assert len(result.items) == 1 and len(result.items[0]) == 1
    assert result.response is not None
    assert all(result.rows[0][key] for key in result.response.primary_keys or [])
    assert len(result.committed_states) == 2
    assert [state.next_token for state in result.saved_states] == ["page-two", None]
    if endpoint == "members":
        assert result.requests[1].query == {
            "maxResults": ("25",),
            "nextToken": ("page-two",),
            "onlyAssociated": ("false",),
        }
    elif endpoint == "usage_statistics":
        assert result.requests[1].json() == {
            "maxResults": 25,
            "nextToken": "page-two",
            "timeRange": "MONTH_TO_DATE",
            "sortBy": {"key": "accountId", "orderBy": "ASC"},
        }
    else:
        assert result.requests[1].json() == {"maxResults": 50, "nextToken": "page-two"}


BUCKET_A = "arn:aws:s3:::bucket-a"
BUCKET_B = "arn:aws:s3:::bucket-b"
BUCKET_C = "arn:aws:s3:::bucket-c"
NOT_FOUND = ScriptedResponse(
    json={"message": "Resource not found."},
    status=404,
    headers={"x-amzn-ErrorType": "ResourceNotFoundException:http://example.com"},
)


def test_bucket_fan_out_walks_buckets_and_child_pages(driver: SourceDriver) -> None:
    result = driver.run(
        "resource_profile_detections",
        [
            ScriptedResponse(json={"buckets": [{"bucketArn": BUCKET_A}, {"bucketArn": BUCKET_B}], "nextToken": "b2"}),
            ScriptedResponse(json={"detections": [{"id": "CREDIT_CARD_NUMBER", "count": 3}], "nextToken": "d2"}),
            ScriptedResponse(json={"detections": [{"id": "AWS_CREDENTIALS", "count": 1}]}),
            NOT_FOUND,
            ScriptedResponse(json={"buckets": [{"bucketArn": BUCKET_C}]}),
            ScriptedResponse(json={"detections": [{"id": "CREDIT_CARD_NUMBER", "count": 7}]}),
        ],
    )
    assert result.raised is None
    assert [(row["bucket_arn"], row["id"], row["count"]) for row in result.rows] == [
        (BUCKET_A, "CREDIT_CARD_NUMBER", 3),
        (BUCKET_A, "AWS_CREDENTIALS", 1),
        (BUCKET_C, "CREDIT_CARD_NUMBER", 7),
    ]
    assert [request.path for request in result.requests] == [
        "/datasources/s3",
        "/resource-profiles/detections",
        "/resource-profiles/detections",
        "/resource-profiles/detections",
        "/datasources/s3",
        "/resource-profiles/detections",
    ]
    assert result.requests[0].json() == {
        "maxResults": 50,
        "sortCriteria": {"attributeName": "bucketName", "orderBy": "ASC"},
    }
    assert result.requests[2].query == {"resourceArn": (BUCKET_A,), "maxResults": ("25",), "nextToken": ("d2",)}
    assert result.requests[3].query == {"resourceArn": (BUCKET_B,), "maxResults": ("25",)}
    assert result.requests[4].json()["nextToken"] == "b2"
    assert [
        (tuple(state.bucket_arns), state.bucket_offset, state.bucket_page_token, state.next_token, state.completed)
        for state in result.saved_states
    ] == [
        ((), 0, None, None, False),
        ((BUCKET_A, BUCKET_B), 0, "b2", "d2", False),
        ((BUCKET_A, BUCKET_B), 1, "b2", None, False),
        ((), 0, "b2", None, False),
        ((), 0, "b2", None, False),
        ((), 0, None, None, True),
        ((), 0, None, None, True),
    ]
    assert result.final_state is not None and result.final_state.completed


@pytest.mark.parametrize(
    "endpoint,body,expected",
    [
        (
            "resource_profiles",
            {"profileUpdatedAt": "2025-01-01T00:00:00Z", "statistics": {"totalItemsSkipped": 2}},
            {"profile_updated_at": dt.datetime(2025, 1, 1, tzinfo=dt.UTC), "statistics": {"totalItemsSkipped": 2}},
        ),
        (
            "resource_profile_artifacts",
            {"artifacts": [{"arn": f"{BUCKET_B}/key.csv", "classificationResultStatus": "SKIPPED"}]},
            {"arn": f"{BUCKET_B}/key.csv", "classification_result_status": "SKIPPED"},
        ),
    ],
)
def test_bucket_fan_out_resumes_from_saved_bucket_page(
    driver: SourceDriver, endpoint: str, body: dict[str, Any], expected: dict[str, Any]
) -> None:
    result = driver.run(
        endpoint,
        [ScriptedResponse(json=body)],
        resume_state=AwsMacieResumeConfig(bucket_arns=(BUCKET_A, BUCKET_B), bucket_offset=1),
    )
    assert result.raised is None
    assert [request.query for request in result.requests] == [{"resourceArn": (BUCKET_B,)}]
    assert result.rows == [{**expected, "bucket_arn": BUCKET_B, "region": "eu-west-1"}]
    assert result.final_state is not None and result.final_state.completed


def test_resume_preserves_original_filter(driver: SourceDriver) -> None:
    result = driver.run(
        "findings",
        [ScriptedResponse(json={"findingIds": []})],
        resume_state=AwsMacieResumeConfig(next_token="saved", since_ms=1234),
        incremental_field="updated_at",
        db_incremental_field_last_value="2025-01-01T00:00:00Z",
    )
    assert result.raised is None
    assert result.items == []
    payload = result.requests[0].json()
    assert payload["nextToken"] == "saved"
    assert payload["findingCriteria"]["criterion"]["updatedAt"]["gte"] == 1234
    assert len(result.committed_states) == 1
    assert result.final_state is not None and result.final_state.completed
    again = driver.run("findings", [], resume_state=result.final_state)
    assert again.raised is None
    assert again.items == []
    assert again.requests == []


def test_failed_hydration_does_not_advance_resume_state(config: AwsMacieSourceConfig, session: Mock) -> None:
    manager = MemoryResumeManager()
    session.request.side_effect = [
        response({"findingIds": ["finding-1"], "nextToken": "page-two"}),
        response({"message": "Try again."}, 500, {"x-amzn-ErrorType": "InternalServerException"}),
    ]
    with pytest.raises(AwsMacieError, match="InternalServerException"):
        list(cast(Iterable[Any], aws_macie_source(config, "findings", manager).items()))
    assert manager.saved == []
    session.close.assert_called_once()


def test_hydration_batches_at_fifty(driver: SourceDriver) -> None:
    ids = [f"finding-{index}" for index in range(51)]
    result = driver.run(
        "findings",
        [
            ScriptedResponse(json={"findingIds": ids}),
            ScriptedResponse(json={"findings": []}),
            ScriptedResponse(json={"findings": []}),
        ],
    )
    assert result.raised is None
    assert result.items == []
    assert [len(request.json()["findingIds"]) for request in result.requests[1:]] == [
        50,
        1,
    ]


def test_repeated_page_token_fails(driver: SourceDriver) -> None:
    result = driver.run("buckets", always(ScriptedResponse(json={"buckets": [], "nextToken": "same"})))
    assert isinstance(result.raised, AwsMacieError)
    assert "RepeatedPaginationToken" in str(result.raised)
    assert len(result.requests) == 2


@pytest.mark.parametrize("schema_name,expected", [(None, True), ("findings", False), ("members", False)])
def test_access_denied_at_create_and_table_selection(
    config: AwsMacieSourceConfig, schema_name: str | None, expected: bool
) -> None:
    with scripted_network(
        [
            ScriptedResponse(
                json={"message": "Not authorized to perform macie2:ListFindings"},
                status=403,
                headers={"x-amzn-ErrorType": "AccessDeniedException:http://example.com"},
            )
        ]
    ) as network:
        valid, message = validate_credentials(config, schema_name)
    assert valid is expected
    assert message is None if expected else "macie2:ListFindings" in (message or "")
    assert len(network.requests_log) == 1


@pytest.mark.parametrize(
    "schema_name,child,expected",
    [
        ("resource_profile_artifacts", NOT_FOUND, True),
        (
            "resource_profiles",
            ScriptedResponse(
                json={"message": "Not authorized"},
                status=403,
                headers={"x-amzn-ErrorType": "AccessDeniedException"},
            ),
            False,
        ),
    ],
)
def test_bucket_profile_permission_probe(
    config: AwsMacieSourceConfig, schema_name: str, child: ScriptedResponse, expected: bool
) -> None:
    with scripted_network([ScriptedResponse(json={"buckets": [{"bucketArn": BUCKET_A}]}), child]) as network:
        valid, _ = validate_credentials(config, schema_name)
    assert valid is expected
    assert network.requests_log[1].query == {"resourceArn": (BUCKET_A,)}


def test_findings_permission_probe_reads_details(config: AwsMacieSourceConfig) -> None:
    with scripted_network(
        [
            ScriptedResponse(json={"findingIds": ["finding-1"]}),
            ScriptedResponse(
                json={"__type": "AccessDeniedException", "message": "Not authorized for macie2:GetFindings"},
                status=403,
            ),
        ]
    ) as network:
        valid, message = validate_credentials(config, "findings")
    assert not valid and "macie2:GetFindings" in (message or "")
    assert network.requests_log[-1].path == "/findings/describe"


@pytest.mark.parametrize("status,code", [(429, "ThrottlingException"), (500, "InternalServerException")])
def test_transient_errors_report_an_unreachable_vendor(config: AwsMacieSourceConfig, status: int, code: str) -> None:
    with scripted_network(
        always(ScriptedResponse(json={"message": "Try again."}, status=status, headers={"x-amzn-ErrorType": code}))
    ) as network:
        assert validate_credentials(config) == (
            False,
            "Couldn't reach AWS Macie to check your credentials. Try again in a few minutes.",
        )
    assert all(request.path == "/findings" for request in network.requests_log)
    assert not any(pattern.lower() in code.lower() for pattern in AwsMacieSource().get_non_retryable_errors())


@pytest.mark.parametrize("region", ["us-east-1.example.com", "https://example.com", "", "us-east-1/path"])
def test_invalid_region_never_sends_credentials(config: AwsMacieSourceConfig, region: str) -> None:
    config.region = region
    with scripted_network([]) as network:
        valid, message = validate_credentials(config)
    assert not valid and "region" in (message or "")
    assert network.requests_log == []


@pytest.mark.parametrize("field", ["aws_access_key_id", "aws_secret_access_key"])
def test_missing_credentials(config: AwsMacieSourceConfig, field: str) -> None:
    setattr(config, field, "")
    with scripted_network([]) as network:
        assert validate_credentials(config) == (False, "Enter both an AWS access key ID and a secret access key.")
    assert network.requests_log == []


def test_unknown_table_and_version(config: AwsMacieSourceConfig, driver: SourceDriver) -> None:
    with scripted_network([]) as network:
        assert validate_credentials(config, "unknown")[0] is False
        with pytest.raises(ValueError, match="Unsupported AWS Macie API version"):
            AwsMacieClient(config, api_version="2017-11-28")
    result = driver.run("unknown", [])
    assert isinstance(result.raised, ValueError)
    assert "Unknown AWS Macie table" in str(result.raised)
    assert network.requests_log == []
    assert result.requests == []


@pytest.mark.parametrize("region,suffix", [("us-east-1", "amazonaws.com"), ("cn-north-1", "amazonaws.com.cn")])
def test_create_probe_and_permanent_credentials(
    config: AwsMacieSourceConfig, session: Mock, region: str, suffix: str
) -> None:
    config.region = region
    config.aws_session_token = None
    session.request.return_value = response({"findingIds": ["finding-1"]})
    assert validate_credentials(config) == (True, None)
    session.request.assert_called_once()
    args, kwargs = session.request.call_args
    assert args[1] == f"https://macie2.{region}.{suffix}/findings"
    assert "X-Amz-Security-Token" not in kwargs["headers"]
    assert json.loads(kwargs["data"])["maxResults"] == 1
    session.close.assert_called_once()


def test_tracked_transport_retries_reads_and_redacts_credentials(config: AwsMacieSourceConfig) -> None:
    with scripted_network([]) as network:
        AwsMacieClient(config)
    options = network.session_options[0]
    assert set(options["redact_values"]) == {"AKIAEXAMPLE", "example-secret", "example-token"}
    retry = options["retry"]
    for method in ("GET", "POST"):
        assert retry.is_retry(method, 429)
        assert retry.is_retry(method, 500)
        assert not retry.is_retry(method, 403)
