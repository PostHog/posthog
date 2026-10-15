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
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_iam_access_analyzer.settings import (
    API_VERSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_iam_access_analyzer.source import (
    AwsIamAccessAnalyzerSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
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


def driver() -> SourceDriver:
    return SourceDriver(AwsIamAccessAnalyzerSource(), CONFIG)


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
    with scripted_network(
        [ScriptedResponse(json={}), ScriptedResponse(status=302, headers={"Location": "/elsewhere"})]
    ) as network:
        client = AwsIamAccessAnalyzerClient(CONFIG, API_VERSION)
        try:
            client.request(endpoint, analyzer=PARENT_A, next_token="a+/=")
            with pytest.raises(AwsIamAccessAnalyzerError) as caught:
                client.request(endpoint, analyzer=PARENT_A, next_token="a+/=")
        finally:
            client.close()

    request = network.requests_log[0]
    assert request.method == method
    assert request.url == "https://access-analyzer.eu-west-1.amazonaws.com" + path
    assert request.json() == payload
    assert request.headers["content-type"] == "application/json"
    assert "x-amz-target" not in request.headers
    assert request.headers["x-amz-security-token"] == "example-token"
    assert "/eu-west-1/access-analyzer/aws4_request" in request.headers["authorization"]
    assert "x-amz-security-token" in request.headers["authorization"]
    assert request.headers["x-amz-date"]
    assert caught.value.code == "HTTP 302"
    assert len(network.requests_log) == 2
    assert network.session_options[0]["redact_values"] == ("AKIAEXAMPLE", "example-secret", "example-token")
    retry = network.session_options[0]["retry"]
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
    first = driver().run(
        endpoint,
        [
            ScriptedResponse(json={"analyzers": [PARENT_A], "nextToken": "parents-2"}),
            ScriptedResponse(json={result_key: [{id_key: "same-id"}], "nextToken": "children-2"}),
        ],
    )
    assert first.rows[0]["analyzer_arn"] == PARENT_A["arn"]
    checkpoint = AwsIamAccessAnalyzerResumeConfig(**json.loads(json.dumps(asdict(first.final_state))))
    assert checkpoint.next_token == "children-2"

    resumed = driver().run(
        endpoint,
        [
            ScriptedResponse(json={result_key: []}),
            ScriptedResponse(json={"analyzers": [], "nextToken": "parents-3"}),
            ScriptedResponse(json={"analyzers": [PARENT_B]}),
            ScriptedResponse(json={result_key: [{id_key: "same-id"}]}),
        ],
        resume_state=checkpoint,
    )

    assert resumed.raised is None
    assert resumed.rows[0]["analyzer_arn"] == PARENT_B["arn"]
    first_request = resumed.requests[0]
    if endpoint == "findings":
        assert first_request.json() == {
            "analyzerArn": PARENT_A["arn"],
            "maxResults": 100,
            "nextToken": "children-2",
        }
    else:
        assert first_request.url.endswith("/example-a/archive-rule?maxResults=100&nextToken=children-2")
    assert resumed.requests[1].url.endswith("nextToken=parents-2")
    assert resumed.requests[2].url.endswith("nextToken=parents-3")
    assert len(resumed.committed_states) == 3
    assert resumed.saved_states[-1].finished


@pytest.mark.parametrize("endpoint,result_key", [("findings", "findings"), ("archive_rules", "archiveRules")])
def test_deleted_analyzer_is_skipped(endpoint: str, result_key: str) -> None:
    result = driver().run(
        endpoint,
        [
            ScriptedResponse(status=404, json={"__type": "ResourceNotFoundException"}),
            ScriptedResponse(json={result_key: [{"id": "remaining"}]}),
        ],
        resume_state=AwsIamAccessAnalyzerResumeConfig(pending_analyzers=[PARENT_A, PARENT_B]),
    )

    assert result.raised is None
    assert result.rows[0]["analyzer_arn"] == PARENT_B["arn"]
    assert result.saved_states[0].pending_analyzers == [PARENT_B]
    assert result.saved_states[-1].finished


def test_child_request_errors_other_than_deleted_analyzers_are_raised() -> None:
    result = driver().run(
        "findings",
        [ScriptedResponse(status=403, json={"__type": "AccessDeniedException"})],
        resume_state=AwsIamAccessAnalyzerResumeConfig(pending_analyzers=[PARENT_A]),
    )
    assert isinstance(result.raised, AwsIamAccessAnalyzerError)
    assert "AccessDeniedException" in str(result.raised)


@pytest.mark.parametrize("endpoint", ["analyzers", "findings", "archive_rules"])
def test_terminal_checkpoint_does_not_restart_the_sync(endpoint: str) -> None:
    result = driver().run(endpoint, [], resume_state=AwsIamAccessAnalyzerResumeConfig(finished=True))
    assert result.raised is None
    assert result.rows == []
    assert result.requests == []


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
    answer = ScriptedResponse(
        status=status,
        json={"__type": f"aws#{code}", "message": "example-secret"},
        headers={"x-amzn-ErrorType": f"{code}:extra"} if header else {},
    )
    with scripted_network(always(answer)):
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


@pytest.mark.parametrize(
    "region,suffix", [("cn-north-1", "amazonaws.com.cn"), ("us-gov-west-1", "amazonaws.com"), ("", "amazonaws.com")]
)
def test_region_controls_endpoint_and_signing_scope(region: str, suffix: str) -> None:
    config = AwsIamAccessAnalyzerSourceConfig(
        aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="example-secret", region=region
    )
    with scripted_network([ScriptedResponse(json={"analyzers": []})]) as network:
        client = AwsIamAccessAnalyzerClient(config)
        try:
            client.request("analyzers")
        finally:
            client.close()
    request = network.requests_log[0]
    expected_region = region or "us-east-1"
    assert request.url.startswith(f"https://access-analyzer.{expected_region}.{suffix}/")
    assert f"/{expected_region}/access-analyzer/" in request.headers["authorization"]
    assert "x-amz-security-token" not in request.headers


@pytest.mark.parametrize(
    "field,value", [("region", "bad.example/path"), ("aws_access_key_id", ""), ("aws_secret_access_key", "")]
)
def test_invalid_configuration_fails_before_network(field: str, value: str) -> None:
    config = AwsIamAccessAnalyzerSourceConfig(aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="example-secret")
    setattr(config, field, value)
    with scripted_network([]) as network:
        valid, message = validate_credentials(config)
    assert not valid
    assert message
    assert network.requests_log == []
    assert network.session_options == []


def test_unknown_version_and_table_fail_before_network() -> None:
    with scripted_network([]) as network:
        assert validate_credentials(CONFIG, api_version="2099-01-01")[0] is False
        assert validate_credentials(CONFIG, schema_name="unknown")[0] is False
        with pytest.raises(ValueError, match="required"):
            AwsIamAccessAnalyzerClient(CONFIG).request("findings")
    result = driver().run("unknown", [])
    assert isinstance(result.raised, ValueError)
    assert "Unknown" in str(result.raised)
    assert network.requests_log == []
    assert result.requests == []


def test_transport_failure_returns_a_safe_validation_message() -> None:
    with patch.object(transport, "make_tracked_session") as factory:
        factory.return_value.request.side_effect = requests.ConnectionError("example-secret")
        valid, message = validate_credentials(CONFIG)
    assert not valid
    assert message is not None and "example-secret" not in message
    factory.return_value.close.assert_called_once()


@pytest.mark.parametrize("status,body", [(500, b"<html>error</html>"), (502, b"[]"), (302, b"")])
def test_non_json_and_redirect_errors_keep_the_http_status(status: int, body: bytes) -> None:
    with scripted_network(always(ScriptedResponse(status=status, body=body))):
        with pytest.raises(AwsIamAccessAnalyzerError) as caught:
            AwsIamAccessAnalyzerClient(CONFIG).request("analyzers")
    assert caught.value.code == f"HTTP {status}"


def test_table_validation_walks_empty_analyzer_pages() -> None:
    with scripted_network(
        [
            ScriptedResponse(json={"analyzers": [], "nextToken": "next"}),
            ScriptedResponse(json={"analyzers": [PARENT_A]}),
            ScriptedResponse(json={"findings": []}),
        ]
    ) as network:
        assert validate_credentials(CONFIG, "findings") == (True, None)
    assert network.requests_log[1].url.endswith("nextToken=next")
    assert network.requests_log[-1].json() == {"maxResults": 1, "analyzerArn": PARENT_A["arn"]}
