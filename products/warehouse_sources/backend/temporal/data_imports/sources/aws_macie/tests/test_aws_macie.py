import json
import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

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
    config: AwsMacieSourceConfig, session: Mock, operation: str, payload: dict[str, Any], method: str, path: str
) -> None:
    client = AwsMacieClient(config)
    client.request(operation, payload)
    args, kwargs = session.request.call_args
    assert args[0] == method
    assert urlsplit(args[1]).netloc == "macie2.eu-west-1.amazonaws.com"
    assert urlsplit(args[1]).path == path
    if method == "POST":
        assert json.loads(kwargs["data"]) == payload
        assert kwargs["headers"]["Content-Type"] == "application/json"
    else:
        assert parse_qs(urlsplit(args[1]).query) == {key: [str(value)] for key, value in payload.items()}
        assert not kwargs["data"]
    headers = kwargs["headers"]
    assert "AWS4-HMAC-SHA256" in headers["Authorization"]
    assert "/eu-west-1/macie2/aws4_request" in headers["Authorization"]
    assert headers["X-Amz-Security-Token"] == "example-token"
    assert "X-Amz-Date" in headers
    assert "X-Amz-Target" not in headers
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == 60


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
    ],
)
@pytest.mark.parametrize("terminal_token", [None, ""])
def test_empty_page_continues_to_terminal_page(
    config: AwsMacieSourceConfig,
    session: Mock,
    endpoint: str,
    key: str,
    item: dict[str, Any],
    terminal_token: str | None,
) -> None:
    session.request.side_effect = [
        response({key: [], "nextToken": "page-two"}),
        response({key: [item], "nextToken": terminal_token}),
    ]
    manager = MemoryResumeManager()
    resource = aws_macie_source(config, endpoint, manager)
    batches = list(cast(Iterable[Any], resource.items()))
    assert len(batches) == 1 and len(batches[0]) == 1
    assert all(batches[0][0][key] for key in resource.primary_keys or [])
    assert manager.safe_points == 2
    assert [state.next_token for state in manager.saved] == ["page-two", None]
    calls = session.request.call_args_list
    if endpoint == "members":
        assert parse_qs(urlsplit(calls[1].args[1]).query) == {
            "maxResults": ["25"],
            "nextToken": ["page-two"],
            "onlyAssociated": ["false"],
        }
    else:
        assert json.loads(calls[1].kwargs["data"]) == {"maxResults": 50, "nextToken": "page-two"}


def test_resume_preserves_original_filter(config: AwsMacieSourceConfig, session: Mock) -> None:
    manager = MemoryResumeManager(AwsMacieResumeConfig(next_token="saved", since_ms=1234))
    session.request.return_value = response({"findingIds": []})
    resource = aws_macie_source(config, "findings", manager, since="2025-01-01T00:00:00Z")
    assert list(cast(Iterable[Any], resource.items())) == []
    payload = json.loads(session.request.call_args.kwargs["data"])
    assert payload["nextToken"] == "saved"
    assert payload["findingCriteria"]["criterion"]["updatedAt"]["gte"] == 1234
    assert manager.safe_points == 1
    session.request.reset_mock()
    assert list(cast(Iterable[Any], resource.items())) == []
    session.request.assert_not_called()


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


def test_hydration_batches_at_fifty(config: AwsMacieSourceConfig, session: Mock) -> None:
    ids = [f"finding-{index}" for index in range(51)]
    session.request.side_effect = [
        response({"findingIds": ids}),
        response({"findings": []}),
        response({"findings": []}),
    ]
    assert list(cast(Iterable[Any], aws_macie_source(config, "findings", MemoryResumeManager()).items())) == []
    assert [len(json.loads(call.kwargs["data"])["findingIds"]) for call in session.request.call_args_list[1:]] == [
        50,
        1,
    ]


def test_repeated_page_token_fails(config: AwsMacieSourceConfig, session: Mock) -> None:
    session.request.return_value = response({"buckets": [], "nextToken": "same"})
    with pytest.raises(AwsMacieError, match="RepeatedPaginationToken"):
        list(cast(Iterable[Any], aws_macie_source(config, "buckets", MemoryResumeManager()).items()))
    assert session.request.call_count == 2


@pytest.mark.parametrize("schema_name,expected", [(None, True), ("findings", False), ("members", False)])
def test_access_denied_at_create_and_table_selection(
    config: AwsMacieSourceConfig, session: Mock, schema_name: str | None, expected: bool
) -> None:
    session.request.return_value = response(
        {"message": "Not authorized to perform macie2:ListFindings"},
        403,
        {"x-amzn-ErrorType": "AccessDeniedException:http://example.com"},
    )
    valid, message = validate_credentials(config, schema_name)
    assert valid is expected
    assert message is None if expected else "macie2:ListFindings" in (message or "")


def test_findings_permission_probe_reads_details(config: AwsMacieSourceConfig, session: Mock) -> None:
    session.request.side_effect = [
        response({"findingIds": ["finding-1"]}),
        response({"__type": "AccessDeniedException", "message": "Not authorized for macie2:GetFindings"}, 403),
    ]
    valid, message = validate_credentials(config, "findings")
    assert not valid and "macie2:GetFindings" in (message or "")
    assert urlsplit(session.request.call_args.args[1]).path == "/findings/describe"


@pytest.mark.parametrize("status,code", [(429, "ThrottlingException"), (500, "InternalServerException")])
def test_transient_errors_propagate(config: AwsMacieSourceConfig, session: Mock, status: int, code: str) -> None:
    session.request.return_value = response({"message": "Try again."}, status, {"x-amzn-ErrorType": code})
    with pytest.raises(AwsMacieError, match=code):
        validate_credentials(config)
    assert not any(pattern.lower() in code.lower() for pattern in AwsMacieSource().get_non_retryable_errors())


@pytest.mark.parametrize("region", ["us-east-1.example.com", "https://example.com", "", "us-east-1/path"])
def test_invalid_region_never_sends_credentials(config: AwsMacieSourceConfig, session: Mock, region: str) -> None:
    config.region = region
    valid, message = validate_credentials(config)
    assert not valid and "region" in (message or "")
    session.request.assert_not_called()


@pytest.mark.parametrize("field", ["aws_access_key_id", "aws_secret_access_key"])
def test_missing_credentials(config: AwsMacieSourceConfig, session: Mock, field: str) -> None:
    setattr(config, field, "")
    assert validate_credentials(config) == (False, "Enter both an AWS access key ID and a secret access key.")
    session.request.assert_not_called()


def test_unknown_table_and_version(config: AwsMacieSourceConfig, session: Mock) -> None:
    assert validate_credentials(config, "unknown")[0] is False
    with pytest.raises(ValueError, match="Unknown AWS Macie table"):
        aws_macie_source(config, "unknown", MemoryResumeManager())
    with pytest.raises(ValueError, match="Unsupported AWS Macie API version"):
        AwsMacieClient(config, api_version="2017-11-28")
    session.request.assert_not_called()


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
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.aws_macie.aws_macie.make_tracked_session"
    ) as factory:
        AwsMacieClient(config)
    options = factory.call_args.kwargs
    assert set(options["redact_values"]) == {"AKIAEXAMPLE", "example-secret", "example-token"}
    retry = options["retry"]
    for method in ("GET", "POST"):
        assert retry.is_retry(method, 429)
        assert retry.is_retry(method, 500)
        assert not retry.is_retry(method, 403)
