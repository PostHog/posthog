import json
import datetime as dt
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any, cast

import pytest
from unittest.mock import patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_iam_access_analyzer import (
    aws_iam_access_analyzer as transport,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_iam_access_analyzer.aws_iam_access_analyzer import (
    AwsIamAccessAnalyzerClient,
    AwsIamAccessAnalyzerError,
    AwsIamAccessAnalyzerResumeConfig,
    aws_iam_access_analyzer_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_iam_access_analyzer.settings import (
    API_VERSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsiamaccessanalyzer import (
    AwsIamAccessAnalyzerSourceConfig,
)

CONFIG = AwsIamAccessAnalyzerSourceConfig(
    aws_access_key_id="AKIAEXAMPLE",
    aws_secret_access_key="example-secret",
    aws_session_token="example-token",
    region="eu-west-1",
)
PARENT_A = {"arn": "arn:aws:access-analyzer:eu-west-1:123456789012:analyzer/example-a", "name": "example-a"}
PARENT_B = {"arn": "arn:aws:access-analyzer:eu-west-1:123456789012:analyzer/example-b", "name": "example-b"}


class FakeManager(ResumableSourceManager[AwsIamAccessAnalyzerResumeConfig]):
    def __init__(self, state: AwsIamAccessAnalyzerResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[AwsIamAccessAnalyzerResumeConfig] = []
        self.safe_points = 0
        self.cleared: bool = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> AwsIamAccessAnalyzerResumeConfig | None:
        return self.state

    def save_state(self, data: AwsIamAccessAnalyzerResumeConfig) -> None:
        self.saved.append(data)

    def safe_point(self) -> None:
        self.safe_points += 1

    def clear_state(self) -> None:
        self.cleared = True


def response(body: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    result.headers.update(headers or {})
    return result


@pytest.mark.parametrize(
    "endpoint,method,path,payload",
    [
        ("analyzers", "GET", "/analyzer?maxResults=100&nextToken=a%2B%2F%3D", None),
        ("findings", "POST", "/findingv2", {"maxResults": 100, "nextToken": "a+/=", "analyzerArn": PARENT_A["arn"]}),
        ("archive_rules", "GET", "/analyzer/example-a/archive-rule?maxResults=100&nextToken=a%2B%2F%3D", None),
    ],
)
def test_requests_use_rest_json_and_sign_the_exact_url_and_body(
    endpoint: str, method: str, path: str, payload: dict[str, Any] | None
) -> None:
    with patch.object(transport, "make_tracked_session") as make_session:
        session = make_session.return_value
        session.request.return_value = response({})
        client = AwsIamAccessAnalyzerClient(CONFIG, API_VERSION)
        client.request(endpoint, analyzer=PARENT_A, next_token="a+/=")

    args, kwargs = session.request.call_args
    assert args == (method, "https://access-analyzer.eu-west-1.amazonaws.com" + path)
    assert (json.loads(kwargs["data"]) if kwargs["data"] else None) == payload
    headers = kwargs["headers"]
    assert headers["Content-Type"] == "application/json"
    assert "X-Amz-Target" not in headers
    assert headers["X-Amz-Security-Token"] == "example-token"
    assert "/eu-west-1/access-analyzer/aws4_request" in headers["Authorization"]
    assert "x-amz-security-token" in headers["Authorization"]
    assert headers["X-Amz-Date"]
    assert kwargs["allow_redirects"] is False
    assert make_session.call_args.kwargs["redact_values"] == ("AKIAEXAMPLE", "example-secret", "example-token")
    retry = make_session.call_args.kwargs["retry"]
    assert retry.is_retry(method, 429)
    assert retry.is_retry(method, 503)
    assert not retry.is_retry(method, 403)


def test_analyzer_pagination_continues_after_empty_page_and_stages_terminal_state() -> None:
    manager = FakeManager()
    with patch.object(transport, "make_tracked_session") as factory:
        session = factory.return_value
        session.request.side_effect = [
            response({"analyzers": [], "nextToken": "next"}),
            response({"analyzers": [{**PARENT_A, "createdAt": "2025-01-01T00:00:00Z"}]}),
        ]
        result = aws_iam_access_analyzer_source(CONFIG, "analyzers", manager, API_VERSION)
        batches = list(cast(Iterable[list[dict[str, Any]]], result.items()))
        assert manager.cleared is False
        assert result.on_complete is not None
        result.on_complete()
    assert len(batches) == 1
    assert batches[0][0]["created_at"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    assert batches[0][0]["region"] == "eu-west-1"
    assert session.request.call_args_list[1].args[1].endswith("&nextToken=next")
    assert manager.saved[0].next_token == "next"
    assert manager.saved[-1].finished
    assert manager.safe_points == 2
    session.close.assert_called_once()
    assert manager.cleared


@pytest.mark.parametrize(
    "endpoint,result_key,id_key", [("findings", "findings", "id"), ("archive_rules", "archiveRules", "ruleName")]
)
def test_child_pages_resume_with_remaining_analyzers_and_parent_cursor(
    endpoint: str, result_key: str, id_key: str
) -> None:
    manager = FakeManager()
    with patch.object(transport, "make_tracked_session") as factory:
        session = factory.return_value
        session.request.side_effect = [
            response({"analyzers": [PARENT_A], "nextToken": "parents-2"}),
            response({result_key: [{id_key: "same-id"}], "nextToken": "children-2"}),
        ]
        first_run = get_rows(CONFIG, endpoint, manager, API_VERSION)
        first_batch = next(first_run)
        checkpoint = AwsIamAccessAnalyzerResumeConfig(**json.loads(json.dumps(asdict(manager.saved[-1]))))
        first_run.close()
        assert checkpoint.next_token == "children-2"
        resumed = FakeManager(checkpoint)
        session.request.reset_mock()
        session.request.side_effect = [
            response({result_key: []}),
            response({"analyzers": [], "nextToken": "parents-3"}),
            response({"analyzers": [PARENT_B]}),
            response({result_key: [{id_key: "same-id"}]}),
        ]
        remaining = list(get_rows(CONFIG, endpoint, resumed, API_VERSION))

    assert first_batch[0]["analyzer_arn"] == PARENT_A["arn"]
    assert remaining[0][0]["analyzer_arn"] == PARENT_B["arn"]
    first_call = session.request.call_args_list[0]
    if endpoint == "findings":
        assert json.loads(first_call.kwargs["data"]) == {
            "analyzerArn": PARENT_A["arn"],
            "maxResults": 100,
            "nextToken": "children-2",
        }
    else:
        assert first_call.args[1].endswith("/example-a/archive-rule?maxResults=100&nextToken=children-2")
    assert session.request.call_args_list[1].args[1].endswith("nextToken=parents-2")
    assert session.request.call_args_list[2].args[1].endswith("nextToken=parents-3")
    assert resumed.safe_points == 3
    assert resumed.saved[-1].finished


@pytest.mark.parametrize("endpoint,result_key", [("findings", "findings"), ("archive_rules", "archiveRules")])
def test_deleted_analyzer_is_skipped(endpoint: str, result_key: str) -> None:
    manager = FakeManager(AwsIamAccessAnalyzerResumeConfig(pending_analyzers=[PARENT_A, PARENT_B]))
    with patch.object(transport, "make_tracked_session") as factory:
        session = factory.return_value
        session.request.side_effect = [
            response({"__type": "ResourceNotFoundException"}, 404),
            response({result_key: [{"id": "remaining"}]}),
        ]
        rows = list(get_rows(CONFIG, endpoint, manager, API_VERSION))

    assert rows[0][0]["analyzer_arn"] == PARENT_B["arn"]
    assert manager.saved[0].pending_analyzers == [PARENT_B]
    assert manager.saved[-1].finished


def test_child_request_errors_other_than_deleted_analyzers_are_raised() -> None:
    manager = FakeManager(AwsIamAccessAnalyzerResumeConfig(pending_analyzers=[PARENT_A]))
    with patch.object(transport, "make_tracked_session") as factory:
        factory.return_value.request.return_value = response({"__type": "AccessDeniedException"}, 403)
        with pytest.raises(AwsIamAccessAnalyzerError, match="AccessDeniedException"):
            list(get_rows(CONFIG, "findings", manager, API_VERSION))


@pytest.mark.parametrize("endpoint", ["analyzers", "findings", "archive_rules"])
def test_terminal_checkpoint_does_not_restart_the_sync(endpoint: str) -> None:
    with patch.object(transport, "make_tracked_session") as factory:
        assert (
            list(get_rows(CONFIG, endpoint, FakeManager(AwsIamAccessAnalyzerResumeConfig(finished=True)), API_VERSION))
            == []
        )
    factory.assert_not_called()


@pytest.mark.parametrize("endpoint", ["findings", "archive_rules"])
def test_no_analyzers_finishes_without_child_requests(endpoint: str) -> None:
    manager = FakeManager()
    with patch.object(transport, "make_tracked_session") as factory:
        factory.return_value.request.return_value = response({"analyzers": []})
        assert list(get_rows(CONFIG, endpoint, manager, API_VERSION)) == []
    factory.return_value.request.assert_called_once()
    assert manager.saved[-1].finished
    assert manager.safe_points == 1


@pytest.mark.parametrize(
    "code,status,header",
    [
        ("AccessDeniedException", 403, True),
        ("UnrecognizedClientException", 403, False),
        ("InvalidSignatureException", 403, False),
        ("SubscriptionRequiredException", 400, False),
        ("ThrottlingException", 429, True),
    ],
)
def test_errors_extract_aws_codes_without_exposing_response_text(code: str, status: int, header: bool) -> None:
    with patch.object(transport, "make_tracked_session") as factory:
        factory.return_value.request.return_value = response(
            {"__type": f"aws#{code}", "message": "example-secret"},
            status,
            {"x-amzn-ErrorType": f"{code}:extra"} if header else {},
        )
        with pytest.raises(AwsIamAccessAnalyzerError) as caught:
            AwsIamAccessAnalyzerClient(CONFIG).request("analyzers")
    assert caught.value.code == code
    assert "example-secret" not in str(caught.value)


@pytest.mark.parametrize("schema_name", [None, "analyzers", "findings", "archive_rules"])
@pytest.mark.parametrize(
    "code",
    [
        "AccessDeniedException",
        "AccessDenied",
        "UnrecognizedClientException",
        "InvalidSignatureException",
        "ExpiredTokenException",
        "SubscriptionRequiredException",
    ],
)
def test_validation_accepts_only_missing_permissions_at_source_creation(schema_name: str | None, code: str) -> None:
    with patch.object(transport, "make_tracked_session") as factory:
        factory.return_value.request.return_value = response({"__type": code}, 403)
        valid, message = validate_credentials(CONFIG, schema_name)
    assert valid == (schema_name is None and code in {"AccessDenied", "AccessDeniedException"})
    assert (message is None) == valid
    factory.return_value.request.assert_called_once()
    factory.return_value.close.assert_called_once()


@pytest.mark.parametrize("schema_name", [None, "findings", "archive_rules"])
def test_validation_checks_child_permissions_only_for_a_selected_table(schema_name: str | None) -> None:
    with patch.object(transport, "make_tracked_session") as factory:
        session = factory.return_value
        session.request.side_effect = [
            response({"analyzers": [PARENT_A]}),
            response({"__type": "AccessDeniedException"}, 403),
        ]
        valid, message = validate_credentials(CONFIG, schema_name)
    assert valid == (schema_name is None)
    assert session.request.call_count == (1 if schema_name is None else 2)
    assert (message is None) == valid
    assert "maxResults=1" in session.request.call_args_list[0].args[1]


@pytest.mark.parametrize(
    "region,suffix", [("cn-north-1", "amazonaws.com.cn"), ("us-gov-west-1", "amazonaws.com"), ("", "amazonaws.com")]
)
def test_region_controls_endpoint_and_signing_scope(region: str, suffix: str) -> None:
    config = AwsIamAccessAnalyzerSourceConfig(
        aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="example-secret", region=region
    )
    with patch.object(transport, "make_tracked_session") as factory:
        factory.return_value.request.return_value = response({"analyzers": []})
        AwsIamAccessAnalyzerClient(config).request("analyzers")
    call = factory.return_value.request.call_args
    expected_region = region or "us-east-1"
    assert call.args[1].startswith(f"https://access-analyzer.{expected_region}.{suffix}/")
    assert f"/{expected_region}/access-analyzer/" in call.kwargs["headers"]["Authorization"]
    assert "X-Amz-Security-Token" not in call.kwargs["headers"]


@pytest.mark.parametrize(
    "field,value", [("region", "bad.example/path"), ("aws_access_key_id", ""), ("aws_secret_access_key", "")]
)
def test_invalid_configuration_fails_before_network(field: str, value: str) -> None:
    config = AwsIamAccessAnalyzerSourceConfig(aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="example-secret")
    setattr(config, field, value)
    with patch.object(transport, "make_tracked_session") as factory:
        valid, message = validate_credentials(config)
    assert not valid
    assert message
    factory.assert_not_called()


def test_unknown_version_and_table_fail_before_network() -> None:
    with patch.object(transport, "make_tracked_session") as factory:
        assert validate_credentials(CONFIG, api_version="2099-01-01")[0] is False
        assert validate_credentials(CONFIG, schema_name="unknown")[0] is False
        with pytest.raises(ValueError, match="Unknown"):
            aws_iam_access_analyzer_source(CONFIG, "unknown", FakeManager(), API_VERSION)
        with pytest.raises(ValueError, match="required"):
            AwsIamAccessAnalyzerClient(CONFIG).request("findings")
    factory.return_value.request.assert_not_called()


def test_transport_failure_returns_a_safe_validation_message() -> None:
    with patch.object(transport, "make_tracked_session") as factory:
        factory.return_value.request.side_effect = requests.ConnectionError("example-secret")
        valid, message = validate_credentials(CONFIG)
    assert not valid
    assert message is not None and "example-secret" not in message
    factory.return_value.close.assert_called_once()


@pytest.mark.parametrize(
    "endpoint,result_key,id_key", [("findings", "findings", "id"), ("archive_rules", "archiveRules", "ruleName")]
)
def test_resume_between_analyzers_does_not_repeat_the_completed_analyzer(
    endpoint: str, result_key: str, id_key: str
) -> None:
    manager = FakeManager()
    with patch.object(transport, "make_tracked_session") as factory:
        session = factory.return_value
        session.request.side_effect = [
            response({"analyzers": [PARENT_A, PARENT_B]}),
            response({result_key: [{id_key: "same-id"}]}),
        ]
        first_run = get_rows(CONFIG, endpoint, manager, API_VERSION)
        next(first_run)
        checkpoint = manager.saved[-1]
        first_run.close()
        resumed = FakeManager(checkpoint)
        session.request.reset_mock()
        session.request.side_effect = [response({result_key: [{id_key: "same-id"}]})]
        rows = list(get_rows(CONFIG, endpoint, resumed, API_VERSION))
    session.request.assert_called_once()
    assert rows[0][0]["analyzer_arn"] == PARENT_B["arn"]
    assert resumed.saved[-1].finished


@pytest.mark.parametrize("status,body", [(500, b"<html>error</html>"), (502, b"[]"), (302, b"")])
def test_non_json_and_redirect_errors_keep_the_http_status(status: int, body: bytes) -> None:
    error_response = response({}, status)
    error_response._content = body
    with patch.object(transport, "make_tracked_session") as factory:
        factory.return_value.request.return_value = error_response
        with pytest.raises(AwsIamAccessAnalyzerError) as caught:
            AwsIamAccessAnalyzerClient(CONFIG).request("analyzers")
    assert caught.value.code == f"HTTP {status}"


def test_table_validation_walks_empty_analyzer_pages() -> None:
    with patch.object(transport, "make_tracked_session") as factory:
        session = factory.return_value
        session.request.side_effect = [
            response({"analyzers": [], "nextToken": "next"}),
            response({"analyzers": [PARENT_A]}),
            response({"findings": []}),
        ]
        assert validate_credentials(CONFIG, "findings") == (True, None)
    assert session.request.call_args_list[1].args[1].endswith("nextToken=next")
    assert json.loads(session.request.call_args.kwargs["data"]) == {"maxResults": 1, "analyzerArn": PARENT_A["arn"]}
