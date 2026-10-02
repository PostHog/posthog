import json
import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import Mock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_security_hub import aws_security_hub
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_security_hub.aws_security_hub import (
    AwsSecurityHubClient,
    AwsSecurityHubError,
    AwsSecurityHubResumeConfig,
    aws_security_hub_source,
    get_rows,
    probe_endpoint_permissions,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_security_hub.source import (
    AwsSecurityHubSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssecurityhub import (
    AwsSecurityHubSourceConfig,
)

VERSION = "2018-10-26"


def config(region: str = "eu-west-1", token: str | None = "fake-session-token") -> AwsSecurityHubSourceConfig:
    return AwsSecurityHubSourceConfig(
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="fake-secret",
        aws_session_token=token,
        region=region,
    )


def response(body: object, status: int = 200, error_type: str | None = None) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    if error_type:
        result.headers["x-amzn-ErrorType"] = error_type
    return result


@pytest.fixture
def session() -> Iterator[Mock]:
    with patch.object(aws_security_hub, "make_tracked_session") as factory:
        factory.return_value.request.return_value = response({})
        yield factory.return_value


def manager(state: AwsSecurityHubResumeConfig | None = None) -> Mock:
    result = Mock(spec=ResumableSourceManager)
    result.can_resume.return_value = state is not None
    result.load_state.return_value = state
    return result


def test_region_is_a_connection_host_field() -> None:
    assert AwsSecurityHubSource().connection_host_fields == ["region"]


@pytest.mark.parametrize(
    "operation,method,path",
    [
        ("GetFindings", "POST", "/findings"),
        ("DescribeStandards", "GET", "/standards"),
        ("GetEnabledStandards", "POST", "/standards/get"),
        ("GetInsights", "POST", "/insights/get"),
    ],
)
def test_signed_rest_requests(session: Mock, operation: str, method: str, path: str) -> None:
    client = AwsSecurityHubClient(config(), VERSION)
    payload = {"MaxResults": 100, "NextToken": "example/+="}
    client.request(operation, payload)
    args, kwargs = session.request.call_args
    url = urlsplit(args[1])
    assert args[0] == method
    assert url.netloc == "securityhub.eu-west-1.amazonaws.com"
    assert url.path == path
    if method == "GET":
        assert parse_qs(url.query) == {"MaxResults": ["100"], "NextToken": ["example/+="]}
        assert kwargs["data"] == b""
    else:
        assert json.loads(kwargs["data"]) == payload
        assert kwargs["headers"]["Content-Type"] == "application/json"
    headers = kwargs["headers"]
    assert "X-Amz-Target" not in headers
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/")
    assert "/eu-west-1/securityhub/aws4_request" in headers["Authorization"]
    assert headers["X-Amz-Security-Token"] == "fake-session-token"
    assert headers["X-Amz-Date"]
    assert kwargs["allow_redirects"] is False


@pytest.mark.parametrize("region,suffix", [("us-east-1", "amazonaws.com"), ("cn-north-1", "amazonaws.com.cn")])
def test_region_and_long_lived_credentials(session: Mock, region: str, suffix: str) -> None:
    AwsSecurityHubClient(config(region, token=None), VERSION).request("GetInsights", {"MaxResults": 1})
    args, kwargs = session.request.call_args
    assert args[1] == f"https://securityhub.{region}.{suffix}/insights/get"
    assert "X-Amz-Security-Token" not in kwargs["headers"]


@pytest.mark.parametrize("region", ["us-east-1.example.com", "us-east-1/path", "", "https://example.com"])
def test_invalid_region_never_sends_credentials(session: Mock, region: str) -> None:
    success, message = validate_credentials(config(region), VERSION)
    assert not success
    assert message and "valid AWS region" in message
    session.request.assert_not_called()


def test_unsupported_version_never_sends_request(session: Mock) -> None:
    with pytest.raises(ValueError, match="Unsupported AWS Security Hub API version"):
        AwsSecurityHubClient(config(), "2099-01-01")
    session.request.assert_not_called()


@pytest.mark.parametrize("terminal_token", [None, ""])
def test_pagination_empty_pages_and_terminal_checkpoint(session: Mock, terminal_token: str | None) -> None:
    session.request.side_effect = [
        response({"Findings": [{"Id": "first", "CreatedAt": "2025-01-01T00:00:00Z"}], "NextToken": "second"}),
        response({"Findings": [], "NextToken": "third"}),
        response({"Findings": [{"Id": "last"}], "NextToken": terminal_token}),
    ]
    resume = manager()
    source = aws_security_hub_source(config(), "findings", VERSION, resume, False, None)
    items = iter(cast(Iterable[Any], source.items()))
    assert next(items) == [{"id": "first", "created_at": dt.datetime(2025, 1, 1, tzinfo=dt.UTC)}]
    assert resume.save_state.call_args.args[0].next_token == "second"
    assert list(items) == [[{"id": "last"}]]
    requests_sent = [json.loads(call.kwargs["data"]) for call in session.request.call_args_list]
    assert [payload.get("NextToken") for payload in requests_sent] == [None, "second", "third"]
    assert resume.save_state.call_args.args[0].finished
    assert resume.safe_point.call_count == 3
    resume.clear_state.assert_not_called()
    assert source.on_complete
    source.on_complete()
    resume.clear_state.assert_called_once()
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "endpoint,result_key,incremental,watermark,expected_start",
    [
        ("findings", "Findings", True, "2025-01-02T03:04:05Z", "2025-01-02T03:04:05+00:00"),
        ("findings", "Findings", True, dt.datetime(2025, 1, 2), "2025-01-02T00:00:00+00:00"),
        ("findings", "Findings", True, None, None),
        ("findings", "Findings", False, "2025-01-02T00:00:00Z", None),
        ("standards", "Standards", True, "2025-01-02T00:00:00Z", None),
        ("enabled_standards", "StandardsSubscriptions", True, "2025-01-02T00:00:00Z", None),
        ("insights", "Insights", True, "2025-01-02T00:00:00Z", None),
    ],
)
def test_sync_filters(
    session: Mock, endpoint: str, result_key: str, incremental: bool, watermark: object, expected_start: str | None
) -> None:
    session.request.return_value = response({result_key: []})
    assert list(get_rows(config(), endpoint, VERSION, manager(), incremental, watermark)) == []
    args, kwargs = session.request.call_args
    payload = json.loads(kwargs["data"]) if kwargs["data"] else parse_qs(urlsplit(args[1]).query)
    if expected_start:
        assert payload["Filters"] == {"UpdatedAt": [{"Start": expected_start}]}
    else:
        assert "Filters" not in payload
    if endpoint == "findings":
        assert payload["SortCriteria"] == [{"Field": "UpdatedAt", "SortOrder": "asc"}]
    else:
        assert "SortCriteria" not in payload


@pytest.mark.parametrize("finished", [False, True])
def test_resume_preserves_original_filter_and_completion(session: Mock, finished: bool) -> None:
    state = AwsSecurityHubResumeConfig(next_token="saved", updated_after="2025-01-01T00:00:00+00:00", finished=finished)
    session.request.return_value = response({"Findings": [{"Id": "remaining"}]})
    batches = list(get_rows(config(), "findings", VERSION, manager(state), True, "2025-02-01T00:00:00Z"))
    if finished:
        assert batches == []
        session.request.assert_not_called()
    else:
        assert batches == [[{"id": "remaining"}]]
        payload = json.loads(session.request.call_args.kwargs["data"])
        assert payload["NextToken"] == "saved"
        assert payload["Filters"] == {"UpdatedAt": [{"Start": state.updated_after}]}


@pytest.mark.parametrize(
    "status,body,header,code,permanent",
    [
        (403, {"__type": "aws#AccessDeniedException", "message": "Denied"}, None, "AccessDeniedException", True),
        (401, {"message": "Denied"}, "InvalidAccessException:http", "InvalidAccessException", True),
        (400, {"code": "UnrecognizedClientException"}, None, "UnrecognizedClientException", True),
        (403, {}, "InvalidSignatureException", "InvalidSignatureException", True),
        (403, {}, "ExpiredTokenException", "ExpiredTokenException", True),
        (
            401,
            {"message": "Account is not subscribed to AWS Security Hub"},
            "InvalidAccessException",
            "SubscriptionRequiredException",
            True,
        ),
        (429, {"__type": "LimitExceededException"}, None, "LimitExceededException", False),
        (500, {"__type": "InternalException"}, None, "InternalException", False),
        (502, "bad gateway", None, "HTTP 502", False),
    ],
)
def test_error_mapping(
    session: Mock, status: int, body: object, header: str | None, code: str, permanent: bool
) -> None:
    session.request.return_value = response(body, status, header)
    with pytest.raises(AwsSecurityHubError) as raised:
        AwsSecurityHubClient(config(), VERSION).request("GetFindings", {"MaxResults": 1})
    assert raised.value.code == code
    errors = AwsSecurityHubSource().get_non_retryable_errors()
    assert any(pattern in str(raised.value) for pattern in errors) is permanent


@pytest.mark.parametrize(
    "schema,code,message,success,reason",
    [
        (None, None, "", True, None),
        (None, "AccessDeniedException", "Denied", True, None),
        (None, "InvalidAccessException", "Denied", True, None),
        ("insights", "AccessDeniedException", "Denied", False, "securityhub:GetInsights"),
        (
            None,
            "InvalidAccessException",
            "Account is not subscribed to AWS Security Hub",
            False,
            "Enable AWS Security Hub",
        ),
        (None, "UnrecognizedClientException", "Invalid key", False, "Check the access key"),
        (None, "ExpiredTokenException", "Expired", False, "session token expired"),
    ],
)
def test_credential_validation(
    session: Mock, schema: str | None, code: str | None, message: str, success: bool, reason: str | None
) -> None:
    session.request.return_value = response({"message": message}, 403 if code else 200, code)
    valid, error = validate_credentials(config(), VERSION, schema)
    assert valid is success
    assert error is None if reason is None else reason in (error or "")
    assert session.request.call_count == 1
    assert json.loads(session.request.call_args.kwargs["data"]) == {"MaxResults": 1}
    session.close.assert_called_once()


@pytest.mark.parametrize("failure", [requests.Timeout(), AwsSecurityHubError("InternalException", "Unavailable")])
def test_permission_probes_do_not_hide_tables_on_transient_errors(session: Mock, failure: Exception) -> None:
    session.request.side_effect = failure
    assert probe_endpoint_permissions(config(), VERSION, ["findings"]) == {"findings": None}


def test_permission_probe_names_missing_permission(session: Mock) -> None:
    session.request.return_value = response({}, 403, "AccessDeniedException")
    permissions = probe_endpoint_permissions(config(), VERSION, ["enabled_standards"])
    assert "securityhub:GetEnabledStandards" in (permissions["enabled_standards"] or "")


def test_finding_identity_and_timestamps_survive_normalization(session: Mock) -> None:
    finding = {
        "Id": "example-finding",
        "ProductArn": "arn:aws:securityhub:eu-west-1::product/example/product-one",
        "AwsAccountId": "111111111111",
        "Region": "eu-west-1",
        "CreatedAt": "2025-01-01T00:00:00Z",
        "UpdatedAt": "2025-02-01T00:00:00Z",
        "Resources": [{"Id": "example-resource", "Type": "Other"}],
        "Severity": {"Label": "LOW"},
    }
    session.request.return_value = response(
        {
            "Findings": [
                finding,
                {**finding, "ProductArn": "arn:aws:securityhub:eu-west-1::product/example/product-two"},
                {**finding, "AwsAccountId": "222222222222"},
                {**finding, "Region": "us-east-1"},
            ]
        }
    )
    source = aws_security_hub_source(config(), "findings", VERSION, manager(), True, None)
    rows = [row for batch in cast(Iterable[Any], source.items()) for row in batch]
    assert source.primary_keys
    assert len({tuple(row[key] for key in source.primary_keys) for row in rows}) == 4
    assert rows[0]["resources"] == finding["Resources"]
    assert rows[0]["severity"] == finding["Severity"]
    assert source.partition_keys
    assert rows[0][source.partition_keys[0]] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    assert rows[0]["updated_at"] == dt.datetime(2025, 2, 1, tzinfo=dt.UTC)


@pytest.mark.parametrize("body", [{}, {"Findings": None}, {"Findings": []}])
def test_empty_terminal_page(session: Mock, body: dict[str, object]) -> None:
    session.request.return_value = response(body)
    resume = manager()
    assert list(get_rows(config(), "findings", VERSION, resume, False, None)) == []
    session.request.assert_called_once()
    assert resume.save_state.call_args.args[0].finished


@pytest.mark.parametrize("missing_field", ["aws_access_key_id", "aws_secret_access_key"])
def test_missing_credentials_do_not_send_request(session: Mock, missing_field: str) -> None:
    source_config = config()
    setattr(source_config, missing_field, "")
    valid, message = validate_credentials(source_config, VERSION)
    assert not valid
    assert message == "Enter both an AWS access key ID and a secret access key."
    session.request.assert_not_called()


def test_unknown_schema_does_not_send_request(session: Mock) -> None:
    valid, message = validate_credentials(config(), VERSION, "unknown")
    assert not valid
    assert message == "Unknown AWS Security Hub table: unknown"
    session.request.assert_not_called()


def test_validation_network_error(session: Mock) -> None:
    session.request.side_effect = requests.Timeout()
    assert validate_credentials(config(), VERSION) == (False, "Could not reach AWS Security Hub. Try again.")
    session.close.assert_called_once()
