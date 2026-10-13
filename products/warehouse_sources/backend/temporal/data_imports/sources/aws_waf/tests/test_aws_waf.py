import json
from collections.abc import Generator, Iterable, Iterator
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_waf.aws_waf import (
    AwsWafClient,
    AwsWafError,
    AwsWafResumeConfig,
    AwsWafRetryableError,
    aws_waf_source,
    error_for_response,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_waf.source import AwsWafSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awswaf import AwsWafSourceConfig

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.aws_waf.aws_waf"


def config(**overrides: Any) -> AwsWafSourceConfig:
    return AwsWafSourceConfig.from_dict(
        {
            "aws_access_key_id": "AKIAEXAMPLE",
            "aws_secret_access_key": "example-secret",
            "aws_session_token": "example-token",
            "aws_region": "eu-west-1",
            "scope": "REGIONAL",
            **overrides,
        }
    )


def response(body: object, status: int = 200, headers: dict[str, str] | None = None) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    result.headers.update(headers or {})
    return result


@pytest.fixture
def session() -> Iterator[MagicMock]:
    with patch(f"{MODULE}.make_tracked_session") as factory:
        factory.return_value.post.return_value = response({"WebACLs": []})
        yield factory.return_value


def manager(state: AwsWafResumeConfig | None = None) -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.load_state.return_value = state
    return result


@pytest.mark.parametrize(
    "scope,region,host,signing_region",
    [
        ("REGIONAL", "eu-west-1", "wafv2.eu-west-1.amazonaws.com", "eu-west-1"),
        ("CLOUDFRONT", "eu-west-1", "wafv2.us-east-1.amazonaws.com", "us-east-1"),
        ("REGIONAL", "cn-north-1", "wafv2.cn-north-1.amazonaws.com.cn", "cn-north-1"),
        ("REGIONAL", "us-gov-west-1", "wafv2.us-gov-west-1.amazonaws.com", "us-gov-west-1"),
    ],
)
@pytest.mark.parametrize("token", [None, "example-token"])
def test_signed_requests(
    session: MagicMock, scope: str, region: str, host: str, signing_region: str, token: str | None
) -> None:
    assert validate_credentials(config(scope=scope, aws_region=region, aws_session_token=token)) == (True, None)
    args, kwargs = session.post.call_args
    assert args == (f"https://{host}/",)
    assert json.loads(kwargs["data"]) == {"Scope": scope, "Limit": 1}
    headers = kwargs["headers"]
    assert headers["X-Amz-Target"] == "AWSWAF_20190729.ListWebACLs"
    assert headers["Content-Type"] == "application/x-amz-json-1.1"
    assert f"/{signing_region}/wafv2/aws4_request" in headers["Authorization"]
    assert "x-amz-target" in headers["Authorization"]
    assert headers["X-Amz-Date"]
    assert headers.get("X-Amz-Security-Token") == token
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == 60
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "table,list_operation,list_key,get_operation,object_key,detail",
    [
        (
            "web_acls",
            "ListWebACLs",
            "WebACLs",
            "GetWebACL",
            "WebACL",
            {"Rules": [{"Name": "rule"}], "DefaultAction": {"Block": {}}},
        ),
        ("rule_groups", "ListRuleGroups", "RuleGroups", "GetRuleGroup", "RuleGroup", {"Capacity": 10, "Rules": []}),
        (
            "ip_sets",
            "ListIPSets",
            "IPSets",
            "GetIPSet",
            "IPSet",
            {"IPAddressVersion": "IPV4", "Addresses": ["192.0.2.0/24"]},
        ),
        (
            "regex_pattern_sets",
            "ListRegexPatternSets",
            "RegexPatternSets",
            "GetRegexPatternSet",
            "RegexPatternSet",
            {"RegularExpressionList": [{"RegexString": "example"}]},
        ),
    ],
)
def test_full_refresh_pagination_and_details(
    session: MagicMock,
    table: str,
    list_operation: str,
    list_key: str,
    get_operation: str,
    object_key: str,
    detail: dict[str, Any],
) -> None:
    summary = {"Id": "00000000-0000-0000-0000-000000000001", "Name": "example"}
    resource = {**summary, "ARN": f"arn:aws:wafv2:eu-west-1:123456789012:regional/{table}/example/id", **detail}
    session.post.side_effect = [
        response({list_key: [], "NextMarker": "page-2"}),
        response({list_key: [summary], "NextMarker": "page-3"}),
        response({object_key: resource, "LockToken": "unused"}),
        response({list_key: [{**summary, "Name": "terminal"}]}),
        response({object_key: {**resource, "ARN": resource["ARN"] + "2", "Name": "terminal"}}),
    ]
    resume = manager()
    stream = aws_waf_source(config(), table, resume)
    batches = list(cast(Iterable[list[dict[str, Any]]], stream.items()))
    assert [row["name"] for batch in batches for row in batch] == ["example", "terminal"]
    row = batches[0][0]
    assert row["arn"] == resource["ARN"]
    assert row["region"] == "eu-west-1"
    assert row["scope"] == "REGIONAL"
    assert "lock_token" not in row
    if table == "web_acls":
        assert row["default_action"] == {"Block": {}}
        assert row["rules"] == [{"Name": "rule"}]
    elif table == "ip_sets":
        assert row["ip_address_version"] == "IPV4"
        assert row["addresses"] == ["192.0.2.0/24"]
    elif table == "regex_pattern_sets":
        assert row["regular_expression_list"] == [{"RegexString": "example"}]
    else:
        assert row["capacity"] == 10
    requests_sent = [call.kwargs for call in session.post.call_args_list]
    assert [request["headers"]["X-Amz-Target"] for request in requests_sent] == [
        f"AWSWAF_20190729.{operation}"
        for operation in [list_operation, list_operation, get_operation, list_operation, get_operation]
    ]
    assert [json.loads(request["data"]) for request in requests_sent] == [
        {"Scope": "REGIONAL", "Limit": 100},
        {"Scope": "REGIONAL", "Limit": 100, "NextMarker": "page-2"},
        {"Scope": "REGIONAL", **summary},
        {"Scope": "REGIONAL", "Limit": 100, "NextMarker": "page-3"},
        {"Scope": "REGIONAL", **summary, "Name": "terminal"},
    ]
    assert [call.args[0] for call in resume.save_state.call_args_list] == [
        AwsWafResumeConfig(next_marker="page-2"),
        AwsWafResumeConfig(next_marker="page-3"),
        AwsWafResumeConfig(),
    ]
    assert resume.safe_point.call_count == 3
    resume.clear_state.assert_not_called()
    assert stream.on_complete is not None
    stream.on_complete()
    resume.clear_state.assert_called_once()


@pytest.mark.parametrize("marker", ["saved-page", None])
def test_resume_from_checkpoint(session: MagicMock, marker: str | None) -> None:
    resume = manager(AwsWafResumeConfig(next_marker=marker))
    assert list(cast(Iterable[Any], aws_waf_source(config(), "web_acls", resume).items())) == []
    payload = json.loads(session.post.call_args.kwargs["data"])
    if marker:
        assert payload["NextMarker"] == marker
    else:
        assert "NextMarker" not in payload
    resume.save_state.assert_called_once_with(AwsWafResumeConfig())
    resume.safe_point.assert_called_once()


def test_checkpoint_is_staged_before_yield(session: MagicMock) -> None:
    session.post.side_effect = [
        response({"WebACLs": [{"Name": "example", "Id": "id"}], "NextMarker": "next"}),
        response({"WebACL": {"ARN": "arn:example", "Name": "example", "Id": "id"}}),
    ]
    resume = manager()
    rows = cast(Generator[list[dict[str, Any]]], aws_waf_source(config(), "web_acls", resume).items())
    assert next(rows)[0]["arn"] == "arn:example"
    resume.save_state.assert_called_once_with(AwsWafResumeConfig(next_marker="next"))
    rows.close()
    resume.clear_state.assert_not_called()
    session.close.assert_called_once()


@pytest.mark.parametrize("error_code", ["WAFNonexistentItemException", "AccessDeniedException"])
def test_resource_deleted_or_denied_during_sync(session: MagicMock, error_code: str) -> None:
    session.post.side_effect = [
        response({"IPSets": [{"Name": "example", "Id": "id"}]}),
        response({"__type": error_code}, 400),
    ]
    resume = manager()
    stream = aws_waf_source(config(), "ip_sets", resume)
    if error_code == "WAFNonexistentItemException":
        assert list(cast(Iterable[Any], stream.items())) == []
        resume.save_state.assert_called_once_with(AwsWafResumeConfig())
        resume.safe_point.assert_called_once()
    else:
        with pytest.raises(AwsWafError, match=error_code):
            list(cast(Iterable[Any], stream.items()))
        resume.save_state.assert_not_called()
    session.close.assert_called_once()


def test_repeated_marker_fails_without_advancing_checkpoint(session: MagicMock) -> None:
    session.post.return_value = response({"WebACLs": [], "NextMarker": "saved"})
    resume = manager(AwsWafResumeConfig(next_marker="saved"))
    with pytest.raises(ValueError, match="repeated pagination marker"):
        list(cast(Iterable[Any], aws_waf_source(config(), "web_acls", resume).items()))
    resume.save_state.assert_not_called()


@pytest.mark.parametrize("schema", [None, "ip_sets"])
@pytest.mark.parametrize("code", ["AccessDenied", "AccessDeniedException", "WAFUnauthorizedOperationException"])
def test_missing_permissions_at_creation_or_schema_probe(session: MagicMock, schema: str | None, code: str) -> None:
    session.post.return_value = response({"__type": f"com.amazonaws.wafv2#{code}"}, 400)
    valid, reason = validate_credentials(config(), schema)
    assert valid is (schema is None)
    if schema:
        assert reason == "Grant wafv2:ListIPSets and wafv2:GetIPSet for this table."
    else:
        assert reason is None
    assert session.post.call_count == 1


def test_schema_probe_checks_detail_permission(session: MagicMock) -> None:
    session.post.side_effect = [
        response({"IPSets": [{"Id": "id", "Name": "example"}]}),
        response({"__type": "AccessDeniedException"}, 400),
    ]
    valid, reason = validate_credentials(config(), "ip_sets")
    assert not valid
    assert reason and "wafv2:GetIPSet" in reason
    assert json.loads(session.post.call_args.kwargs["data"]) == {"Scope": "REGIONAL", "Id": "id", "Name": "example"}


@pytest.mark.parametrize(
    "code,expected",
    [
        ("UnrecognizedClientException", "access key"),
        ("InvalidClientTokenId", "access key"),
        ("InvalidSignatureException", "signature"),
        ("SignatureDoesNotMatch", "signature"),
        ("ExpiredTokenException", "expired"),
        ("ExpiredToken", "expired"),
        ("OptInRequired", "Enable AWS WAF"),
        ("SubscriptionRequiredException", "subscription"),
    ],
)
def test_credential_errors_are_actionable_and_non_retryable(session: MagicMock, code: str, expected: str) -> None:
    error_response = response({"__type": code, "Message": "AWS rejected this request."}, 400)
    session.post.return_value = error_response
    valid, reason = validate_credentials(config())
    assert not valid and reason and expected in reason
    error = error_for_response(error_response)
    mapped = [
        message for pattern, message in AwsWafSource().get_non_retryable_errors().items() if pattern in str(error)
    ]
    assert mapped and all(message and expected in message for message in mapped)
    assert session.post.call_count == 1


@pytest.mark.parametrize(
    "status,body,headers,code,retryable",
    [
        (400, {"__type": "aws#ThrottlingException"}, {}, "ThrottlingException", True),
        (429, {}, {"Retry-After": "3"}, "HTTP 429", True),
        (500, {"__type": "WAFInternalErrorException"}, {}, "WAFInternalErrorException", True),
        (503, "unavailable", {}, "HTTP 503", True),
        (400, {"__type": "WAFInvalidParameterException"}, {}, "WAFInvalidParameterException", False),
        (403, {}, {"x-amzn-ErrorType": "AccessDeniedException:http"}, "AccessDeniedException", False),
        (302, {}, {}, "HTTP 302", False),
    ],
)
def test_error_classification(status: int, body: object, headers: dict[str, str], code: str, retryable: bool) -> None:
    error = error_for_response(response(body, status, headers))
    assert error.code == code
    assert isinstance(error, AwsWafRetryableError) is retryable
    if status == 429:
        assert isinstance(error, AwsWafRetryableError) and error.retry_after == 3


@pytest.mark.parametrize("status,code", [(400, "ThrottlingException"), (429, "TooManyRequests"), (503, "Unavailable")])
def test_transient_errors_retry_without_transport_retry(session: MagicMock, status: int, code: str) -> None:
    session.post.side_effect = [response({"__type": code}, status), response({"WebACLs": []})]
    client = AwsWafClient(config())
    request = client.request.retry_with(wait=wait_none())  # type: ignore[attr-defined]
    assert request(client, "ListWebACLs", {"Scope": "REGIONAL", "Limit": 1}) == {"WebACLs": []}
    assert session.post.call_count == 2


def test_retries_stop_after_five_attempts(session: MagicMock) -> None:
    session.post.return_value = response({"__type": "ThrottlingException"}, 400)
    client = AwsWafClient(config())
    request = client.request.retry_with(wait=wait_none())  # type: ignore[attr-defined]
    with pytest.raises(AwsWafRetryableError, match="ThrottlingException"):
        request(client, "ListWebACLs", {"Scope": "REGIONAL", "Limit": 1})
    assert session.post.call_count == 5


def test_tracked_transport_redacts_secrets_and_disables_nested_retries() -> None:
    with patch(f"{MODULE}.make_tracked_session") as factory:
        AwsWafClient(config())
    assert factory.call_args.kwargs["retry"].total == 0
    assert set(factory.call_args.kwargs["redact_values"]) == {"example-secret", "example-token"}


def test_service_errors_do_not_become_credential_failures(session: MagicMock) -> None:
    session.post.return_value = response({"__type": "WAFInvalidParameterException"}, 400)
    with pytest.raises(AwsWafError, match="WAFInvalidParameterException"):
        validate_credentials(config())
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"aws_access_key_id": ""}, "access key ID"),
        ({"aws_secret_access_key": ""}, "secret access key"),
        ({"scope": "invalid"}, "scope"),
        ({"aws_region": "us-east-1.example.com"}, "region"),
        ({"aws_region": "https://example.com"}, "region"),
    ],
)
def test_invalid_configuration_does_not_send_credentials(
    session: MagicMock, overrides: dict[str, str], expected: str
) -> None:
    valid, reason = validate_credentials(config(**overrides))
    assert not valid and reason and expected in reason
    session.post.assert_not_called()


def test_unknown_schema_and_api_version_fail_before_requests(session: MagicMock) -> None:
    assert validate_credentials(config(), "unknown") == (False, "Unknown AWS WAF table: unknown")
    valid, reason = validate_credentials(config(), api_version="2015-08-24")
    assert not valid and reason and "Unsupported AWS WAF API version" in reason
    with pytest.raises(ValueError, match="Unknown AWS WAF table"):
        aws_waf_source(config(), "unknown", manager())
    session.post.assert_not_called()
