import json
import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest import mock

import requests
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_guardduty import aws_guardduty
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_guardduty.aws_guardduty import (
    AwsGuarddutyClient,
    AwsGuarddutyError,
    AwsGuarddutyResumeConfig,
    AwsGuarddutyThrottledError,
    aws_guardduty_source,
    error_for_response,
    get_rows,
    validate_credentials,
    watermark_milliseconds,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_guardduty.source import AwsGuarddutySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsguardduty import (
    AwsGuarddutySourceConfig,
)

VERSION = "2017-11-28"
UPDATED_AT = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)


class FakeResumeManager(ResumableSourceManager[AwsGuarddutyResumeConfig]):
    def __init__(self, state: AwsGuarddutyResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[AwsGuarddutyResumeConfig] = []
        self.cleared: bool = False
        self.safe_points = 0

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> AwsGuarddutyResumeConfig | None:
        return self.state

    def save_state(self, data: AwsGuarddutyResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True

    def safe_point(self) -> None:
        self.safe_points += 1


def response(
    payload: dict[str, Any] | None = None, status: int = 200, headers: dict[str, str] | None = None
) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload or {}).encode()
    result.headers.update(headers or {})
    return result


@pytest.fixture
def config() -> AwsGuarddutySourceConfig:
    return AwsGuarddutySourceConfig(
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="example-secret",
        aws_session_token="example-session-token",
        aws_region="us-east-1",
    )


@pytest.fixture
def session() -> Iterator[mock.MagicMock]:
    with mock.patch.object(aws_guardduty, "make_tracked_session") as factory:
        factory.return_value.request.return_value = response()
        yield factory.return_value


@pytest.mark.parametrize(
    "operation,payload,method,path,query,body",
    [
        ("ListDetectors", {"MaxResults": 1}, "GET", "/detector", {"maxResults": ["1"]}, None),
        ("GetDetector", {"DetectorId": "detector-example"}, "GET", "/detector/detector-example", {}, None),
        (
            "ListMembers",
            {"DetectorId": "detector-example", "MaxResults": 50, "NextToken": "a+b/=", "OnlyAssociated": "false"},
            "GET",
            "/detector/detector-example/member",
            {"maxResults": ["50"], "nextToken": ["a+b/="], "onlyAssociated": ["false"]},
            None,
        ),
        (
            "ListFindings",
            {"DetectorId": "detector-example", "MaxResults": 50, "NextToken": "next-page"},
            "POST",
            "/detector/detector-example/findings",
            {},
            {"maxResults": 50, "nextToken": "next-page"},
        ),
        (
            "GetFindings",
            {"DetectorId": "detector-example", "FindingIds": ["finding-example"]},
            "POST",
            "/detector/detector-example/findings/get",
            {},
            {"findingIds": ["finding-example"]},
        ),
    ],
)
def test_signed_rest_requests(
    config: AwsGuarddutySourceConfig,
    session: mock.MagicMock,
    operation: str,
    payload: dict[str, Any],
    method: str,
    path: str,
    query: dict[str, list[str]],
    body: dict[str, Any] | None,
) -> None:
    client = AwsGuarddutyClient(config, VERSION)
    client.request(operation, payload)
    call = session.request.call_args
    assert call.args[0] == method
    url = urlsplit(call.args[1])
    assert url.netloc == "guardduty.us-east-1.amazonaws.com"
    assert url.path == path
    assert parse_qs(url.query) == query
    assert (json.loads(call.kwargs["data"]) if body is not None else call.kwargs["data"]) == (body or b"")
    headers = call.kwargs["headers"]
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/")
    assert "/us-east-1/guardduty/aws4_request" in headers["Authorization"]
    assert "X-Amz-Date" in headers
    assert headers["X-Amz-Security-Token"] == "example-session-token"
    assert "X-Amz-Target" not in headers
    if body is not None:
        assert headers["Content-Type"] == "application/json"
    assert call.kwargs["timeout"] == 60
    assert call.kwargs["allow_redirects"] is False
    factory = aws_guardduty.make_tracked_session
    assert isinstance(factory, mock.Mock)
    assert "example-secret" in factory.call_args.kwargs["redact_values"]
    assert "example-session-token" in factory.call_args.kwargs["redact_values"]


@pytest.mark.parametrize("region,suffix", [("eu-west-1", "amazonaws.com"), ("cn-north-1", "amazonaws.com.cn")])
def test_region_and_credentials_without_session_token(
    config: AwsGuarddutySourceConfig, session: mock.MagicMock, region: str, suffix: str
) -> None:
    config.aws_region = region
    config.aws_session_token = None
    AwsGuarddutyClient(config, VERSION).request("ListDetectors", {})
    call = session.request.call_args
    assert call.args[1] == f"https://guardduty.{region}.{suffix}/detector"
    assert f"/{region}/guardduty/aws4_request" in call.kwargs["headers"]["Authorization"]
    assert "X-Amz-Security-Token" not in call.kwargs["headers"]


@pytest.mark.parametrize("incremental", [True, False])
@pytest.mark.parametrize("terminal", [{}, {"nextToken": None}, {"nextToken": ""}])
def test_findings_pages_hydration_and_time_filter(
    config: AwsGuarddutySourceConfig, session: mock.MagicMock, incremental: bool, terminal: dict[str, Any]
) -> None:
    session.request.side_effect = [
        response({"detectorIds": [], "nextToken": "detectors-next"}),
        response({"detectorIds": ["detector-example"]}),
        response({"findingIds": [], "nextToken": "findings-next"}),
        response({"findingIds": ["finding-example"], **terminal}),
        response(
            {
                "findings": [
                    {
                        "id": "finding-example",
                        "arn": "arn:aws:guardduty:us-east-1:111111111111:detector/example/finding/example",
                        "createdAt": "2024-12-01T00:00:00Z",
                        "updatedAt": "2025-01-01T00:00:00Z",
                        "resource": {"resourceType": "Instance", "instanceDetails": {"instanceId": "i-example"}},
                    }
                ]
            }
        ),
    ]
    manager = FakeResumeManager()
    inputs = mock.Mock(
        spec=SourceInputs,
        schema_name="findings",
        api_version=VERSION,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=UPDATED_AT,
    )
    resource = AwsGuarddutySource().source_for_pipeline(config, manager, inputs)
    batches = list(cast(Iterable[Any], resource.items()))
    assert len(batches) == 1
    row = batches[0][0]
    assert row["updated_at"] == UPDATED_AT
    assert row["created_at"] == dt.datetime(2024, 12, 1, tzinfo=dt.UTC)
    assert row["source_detector_id"] == "detector-example"
    assert row["resource"]["instanceDetails"]["instanceId"] == "i-example"
    calls = session.request.call_args_list
    assert parse_qs(urlsplit(calls[1].args[1]).query)["nextToken"] == ["detectors-next"]
    for call in calls[2:4]:
        payload = json.loads(call.kwargs["data"])
        assert payload["maxResults"] == 50
        assert payload["sortCriteria"] == {"attributeName": "updatedAt", "orderBy": "ASC"}
        if incremental:
            assert payload["findingCriteria"] == {"criterion": {"updatedAt": {"greaterThanOrEqual": 1735689600000}}}
        else:
            assert "findingCriteria" not in payload
    assert json.loads(calls[3].kwargs["data"])["nextToken"] == "findings-next"
    assert json.loads(calls[4].kwargs["data"]) == {
        "findingIds": ["finding-example"],
        "sortCriteria": {"attributeName": "updatedAt", "orderBy": "ASC"},
    }
    assert manager.safe_points == 2
    assert manager.saved[-1].detector_ids == []
    assert not manager.cleared
    assert resource.on_complete is not None
    resource.on_complete()
    assert resource.partition_keys == ["created_at"]
    assert resource.sort_mode == "desc"
    session.close.assert_called_once()
    assert manager.cleared


def test_resume_preserves_filter_and_advances_after_yield(
    config: AwsGuarddutySourceConfig, session: mock.MagicMock
) -> None:
    manager = FakeResumeManager(
        AwsGuarddutyResumeConfig(
            detector_ids=["detector-example"], next_token="saved-page", updated_since_ms=1735689600000
        )
    )
    session.request.side_effect = [
        response({"findingIds": ["finding-example"]}),
        response({"findings": [{"id": "finding-example", "arn": "arn:example", "updatedAt": "2025-01-01T00:00:00Z"}]}),
    ]
    rows = get_rows(config, "findings", VERSION, manager, "2025-02-01T00:00:00Z")
    assert next(rows)[0]["id"] == "finding-example"
    assert manager.saved == []
    assert list(rows) == []
    payload = json.loads(session.request.call_args_list[0].kwargs["data"])
    assert payload["nextToken"] == "saved-page"
    assert payload["findingCriteria"]["criterion"]["updatedAt"]["greaterThanOrEqual"] == 1735689600000
    assert manager.saved[-1].detector_ids == []


@pytest.mark.parametrize("endpoint", ["findings", "members", "detectors"])
def test_completed_resume_does_not_repeat_requests(
    config: AwsGuarddutySourceConfig, session: mock.MagicMock, endpoint: str
) -> None:
    manager = FakeResumeManager(AwsGuarddutyResumeConfig(detector_ids=[]))
    assert list(get_rows(config, endpoint, VERSION, manager, None)) == []
    session.request.assert_not_called()
    session.close.assert_called_once()


def test_members_pagination_and_parent_keys(config: AwsGuarddutySourceConfig, session: mock.MagicMock) -> None:
    member = {"accountId": "111111111111", "detectorId": "member-detector", "relationshipStatus": "Enabled"}
    session.request.side_effect = [
        response({"detectorIds": ["administrator-a", "administrator-b"]}),
        response({"members": [member], "nextToken": "next-page"}),
        response({"members": []}),
        response({"members": [member]}),
    ]
    manager = FakeResumeManager()
    resource = aws_guardduty_source(config, "members", VERSION, manager, UPDATED_AT)
    rows = [row for batch in cast(Iterable[Any], resource.items()) for row in batch]
    assert len({tuple(row[key] for key in resource.primary_keys or []) for row in rows}) == 2
    assert rows[0]["detector_id"] == "member-detector"
    for call in session.request.call_args_list[1:]:
        query = parse_qs(urlsplit(call.args[1]).query)
        assert query["onlyAssociated"] == ["false"]
        assert query["maxResults"] == ["50"]
        assert call.kwargs["data"] == b""
    assert manager.saved[1].detector_ids == ["administrator-b"]
    assert manager.saved[1].next_token is None
    assert "nextToken" not in parse_qs(urlsplit(session.request.call_args_list[3].args[1]).query)


def test_detector_details(config: AwsGuarddutySourceConfig, session: mock.MagicMock) -> None:
    session.request.side_effect = [
        response({"detectorIds": ["detector-example"]}),
        response({"status": "ENABLED", "createdAt": "2025-01-01T00:00:00Z", "tags": {"purpose": "example"}}),
    ]
    rows = list(get_rows(config, "detectors", VERSION, FakeResumeManager(), None))
    assert rows == [
        [
            {
                "status": "ENABLED",
                "created_at": UPDATED_AT,
                "tags": {"purpose": "example"},
                "region": "us-east-1",
                "source_detector_id": "detector-example",
            }
        ]
    ]
    assert session.request.call_args.args[1].endswith("/detector/detector-example")


def test_empty_region_does_not_request_children(config: AwsGuarddutySourceConfig, session: mock.MagicMock) -> None:
    session.request.return_value = response({"detectorIds": []})
    assert list(get_rows(config, "findings", VERSION, FakeResumeManager(), None)) == []
    session.request.assert_called_once()


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (UPDATED_AT, 1735689600000),
        ("2025-01-01T01:00:00.123+01:00", 1735689600123),
        ("2025-01-01T00:00:00", 1735689600000),
    ],
)
def test_watermark_conversion(value: dt.datetime | str | None, expected: int | None) -> None:
    assert watermark_milliseconds(value) == expected


@pytest.mark.parametrize(
    "status,payload,headers,code,retryable",
    [
        (403, {"message": "Access denied"}, {}, "AccessDenied", False),
        (403, {"__type": "com.amazonaws#AccessDeniedException"}, {}, "AccessDeniedException", False),
        (
            400,
            {"message": "Invalid key"},
            {"x-amzn-ErrorType": "UnrecognizedClientException:example"},
            "UnrecognizedClientException",
            False,
        ),
        (400, {"code": "InvalidSignatureException"}, {}, "InvalidSignatureException", False),
        (400, {"code": "ExpiredTokenException"}, {}, "ExpiredTokenException", False),
        (400, {"message": "AWS subscription is required"}, {}, "SubscriptionRequiredException", False),
        (400, {"message": "The account is not subscribed to the service."}, {}, "SubscriptionRequiredException", False),
        (400, {"__type": "ThrottlingException"}, {}, "ThrottlingException", True),
        (429, {"__type": "ThrottlingException"}, {}, "ThrottlingException", False),
        (500, {"__type": "InternalServerErrorException"}, {}, "InternalServerErrorException", False),
    ],
)
def test_error_mapping(
    status: int, payload: dict[str, Any], headers: dict[str, str], code: str, retryable: bool
) -> None:
    error = error_for_response(response(payload, status, headers))
    assert error.code == code
    assert isinstance(error, AwsGuarddutyThrottledError) == retryable
    if code not in {"ThrottlingException", "InternalServerErrorException"}:
        messages = AwsGuarddutySource().get_non_retryable_errors()
        assert any(pattern in str(error) and message for pattern, message in messages.items())


@pytest.mark.parametrize("status", [403, 502])
def test_non_json_errors(status: int) -> None:
    result = response(status=status)
    result._content = b"upstream error"
    assert error_for_response(result).code == ("AccessDenied" if status == 403 else "HTTP 502")


@pytest.mark.parametrize(
    "status,code,attempts",
    [(400, "ThrottlingException", 2), (429, "ThrottlingException", 1), (500, "InternalServerErrorException", 1)],
)
def test_only_body_throttles_get_application_retries(
    config: AwsGuarddutySourceConfig, session: mock.MagicMock, status: int, code: str, attempts: int
) -> None:
    session.request.side_effect = [response({"code": code}, status), response({"detectorIds": []})]
    client = AwsGuarddutyClient(config, VERSION)
    with mock.patch.object(AwsGuarddutyClient.request.retry, "wait", wait_none()):  # type: ignore[attr-defined]
        if attempts == 1:
            with pytest.raises(AwsGuarddutyError):
                client.request("ListDetectors", {})
        else:
            assert client.request("ListDetectors", {}) == {"detectorIds": []}
    assert session.request.call_count == attempts


@pytest.mark.parametrize("schema_name", [None, "findings", "detectors", "members"])
def test_permission_denial_only_accepted_at_create(
    config: AwsGuarddutySourceConfig, session: mock.MagicMock, schema_name: str | None
) -> None:
    session.request.return_value = response({"__type": "AccessDeniedException", "message": "Access denied"}, 403)
    valid, message = validate_credentials(config, VERSION, schema_name)
    assert valid is (schema_name is None)
    if schema_name:
        assert message and "guardduty:ListDetectors" in message
    else:
        assert message is None
    session.request.assert_called_once()
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "code",
    [
        "UnrecognizedClientException",
        "InvalidSignatureException",
        "ExpiredTokenException",
        "SubscriptionRequiredException",
    ],
)
def test_invalid_credentials_rejected(config: AwsGuarddutySourceConfig, session: mock.MagicMock, code: str) -> None:
    session.request.return_value = response({"__type": code}, 400)
    valid, message = validate_credentials(config, VERSION)
    assert not valid and message
    assert "AWS GuardDuty request failed" not in message


@pytest.mark.parametrize("schema_name", [None, "findings", "detectors", "members"])
def test_no_detector_validation(
    config: AwsGuarddutySourceConfig, session: mock.MagicMock, schema_name: str | None
) -> None:
    session.request.return_value = response({"detectorIds": []})
    valid, message = validate_credentials(config, VERSION, schema_name)
    assert valid is (schema_name is None)
    assert (
        message is None
        if schema_name is None
        else message == "Enable GuardDuty in the selected AWS region, then reconnect."
    )


@pytest.mark.parametrize(
    "schema_name,path", [("findings", "/findings"), ("members", "/member"), ("detectors", "/detector/detector-example")]
)
def test_endpoint_validation_calls_its_read_operation(
    config: AwsGuarddutySourceConfig, session: mock.MagicMock, schema_name: str, path: str
) -> None:
    session.request.side_effect = [response({"detectorIds": ["detector-example"]}), response()]
    assert validate_credentials(config, VERSION, schema_name) == (True, None)
    assert urlsplit(session.request.call_args.args[1]).path.endswith(path)


def test_findings_validation_checks_hydration_permission(
    config: AwsGuarddutySourceConfig, session: mock.MagicMock
) -> None:
    session.request.side_effect = [
        response({"detectorIds": ["detector-example"]}),
        response({"findingIds": ["finding-example"]}),
        response({"code": "AccessDeniedException"}, 403),
    ]
    valid, message = validate_credentials(config, VERSION, "findings")
    assert not valid and message and "guardduty:GetFindings" in message
    assert session.request.call_args.args[1].endswith("/findings/get")


def test_server_errors_propagate_from_validation(config: AwsGuarddutySourceConfig, session: mock.MagicMock) -> None:
    session.request.return_value = response({"__type": "InternalServerErrorException"}, 500)
    with pytest.raises(AwsGuarddutyError, match="InternalServerErrorException"):
        validate_credentials(config, VERSION)
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "field_name,value,message",
    [
        ("aws_region", "us-east-1.example.com/", "valid AWS region"),
        ("aws_region", "us-east-1\n", "valid AWS region"),
        ("aws_access_key_id", "", "Enter both"),
        ("aws_secret_access_key", "", "Enter both"),
    ],
)
def test_invalid_configuration_never_sends_request(
    config: AwsGuarddutySourceConfig, session: mock.MagicMock, field_name: str, value: str, message: str
) -> None:
    setattr(config, field_name, value)
    valid, error = validate_credentials(config, VERSION)
    assert not valid and error and message in error
    session.request.assert_not_called()


def test_unknown_version_and_table(config: AwsGuarddutySourceConfig, session: mock.MagicMock) -> None:
    assert validate_credentials(config, "2099-01-01")[0] is False
    assert validate_credentials(config, VERSION, "unknown") == (False, "Unknown GuardDuty table: unknown")
    with pytest.raises(UnknownResourceError):
        aws_guardduty_source(config, "unknown", VERSION, FakeResumeManager(), None)
    session.request.assert_not_called()


def test_hydration_failure_keeps_checkpoint(config: AwsGuarddutySourceConfig, session: mock.MagicMock) -> None:
    session.request.side_effect = [
        response({"detectorIds": ["detector-example"]}),
        response({"findingIds": ["finding-example"], "nextToken": "next-page"}),
        response({"code": "InternalServerErrorException"}, 500),
    ]
    manager = FakeResumeManager()
    with pytest.raises(AwsGuarddutyError):
        list(get_rows(config, "findings", VERSION, manager, None))
    assert manager.saved == []
    assert not manager.cleared
    session.close.assert_called_once()


@pytest.mark.parametrize("endpoint", ["findings", "members"])
def test_repeated_token_fails_without_looping(
    config: AwsGuarddutySourceConfig, session: mock.MagicMock, endpoint: str
) -> None:
    manager = FakeResumeManager(AwsGuarddutyResumeConfig(detector_ids=["detector-example"], next_token="same-token"))
    session.request.return_value = response({"nextToken": "same-token"})
    with pytest.raises(ValueError, match="repeated a page token"):
        list(get_rows(config, endpoint, VERSION, manager, None))
    session.request.assert_called_once()


def test_repeated_detector_token_fails_without_looping(
    config: AwsGuarddutySourceConfig, session: mock.MagicMock
) -> None:
    session.request.return_value = response({"detectorIds": [], "nextToken": "same-token"})
    with pytest.raises(ValueError, match="repeated a page token"):
        list(get_rows(config, "detectors", VERSION, FakeResumeManager(), None))
    assert session.request.call_count == 2
    session.close.assert_called_once()


@pytest.mark.parametrize("endpoint", ["findings", "members"])
def test_cyclic_token_fails_without_looping(
    config: AwsGuarddutySourceConfig, session: mock.MagicMock, endpoint: str
) -> None:
    manager = FakeResumeManager(AwsGuarddutyResumeConfig(detector_ids=["detector-example"]))
    session.request.side_effect = [
        response({"nextToken": "token-a"}),
        response({"nextToken": "token-b"}),
        response({"nextToken": "token-a"}),
    ]
    with pytest.raises(ValueError, match="repeated a page token"):
        list(get_rows(config, endpoint, VERSION, manager, None))
    assert manager.saved[-1].next_token == "token-b"
    assert session.request.call_count == 3


def test_cyclic_detector_token_fails_without_looping(config: AwsGuarddutySourceConfig, session: mock.MagicMock) -> None:
    session.request.side_effect = [
        response({"detectorIds": [], "nextToken": "token-a"}),
        response({"detectorIds": [], "nextToken": "token-b"}),
        response({"detectorIds": [], "nextToken": "token-a"}),
    ]
    with pytest.raises(ValueError, match="repeated a page token"):
        list(get_rows(config, "detectors", VERSION, FakeResumeManager(), None))
    assert session.request.call_count == 3
    session.close.assert_called_once()


def test_invalid_response_fails_instead_of_silently_finishing(
    config: AwsGuarddutySourceConfig, session: mock.MagicMock
) -> None:
    result = response()
    result._content = b"[]"
    session.request.return_value = result
    with pytest.raises(ValueError, match="invalid response"):
        list(get_rows(config, "findings", VERSION, FakeResumeManager(), None))
    session.close.assert_called_once()
