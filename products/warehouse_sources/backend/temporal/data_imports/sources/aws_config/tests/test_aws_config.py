import json
import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_config import aws_config
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_config.aws_config import (
    AwsConfigClient,
    AwsConfigError,
    AwsConfigResumeConfig,
    AwsConfigThrottledError,
    aws_config_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsconfig import (
    AwsConfigSourceConfig,
)


def make_config(**overrides: Any) -> AwsConfigSourceConfig:
    return AwsConfigSourceConfig.from_dict(
        {
            "aws_access_key_id": "AKIAEXAMPLE",
            "aws_secret_access_key": "example-secret",
            "aws_session_token": "example-session",
            "region": "eu-west-1",
            **overrides,
        }
    )


def make_response(body: Any, status: int = 200, headers: dict[str, str] | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    response.headers.update(headers or {})
    return response


@pytest.fixture
def session() -> Iterator[MagicMock]:
    with patch.object(aws_config, "make_tracked_session") as factory:
        factory.return_value.post.return_value = make_response({})
        yield factory.return_value


def make_manager(state: AwsConfigResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = state is not None
    manager.load_state.return_value = state
    return manager


@pytest.mark.parametrize(
    "region,token,host,signing_region",
    [
        ("eu-west-1", "example-session", "config.eu-west-1.amazonaws.com", "eu-west-1"),
        ("cn-north-1", None, "config.cn-north-1.amazonaws.com.cn", "cn-north-1"),
        ("us-gov-west-1", None, "config.us-gov-west-1.amazonaws.com", "us-gov-west-1"),
        (None, None, "config.us-east-1.amazonaws.com", "us-east-1"),
    ],
)
def test_signed_tracked_request(region: str | None, token: str | None, host: str, signing_region: str) -> None:
    with patch.object(aws_config, "make_tracked_session") as factory:
        factory.return_value.post.return_value = make_response({"ConfigRules": []})
        client = AwsConfigClient(make_config(region=region, aws_session_token=token), "2014-11-12")
        assert client.request("DescribeConfigRules", {"NextToken": "page-2"}) == {"ConfigRules": []}

    call = factory.return_value.post.call_args
    assert call.args == (f"https://{host}/",)
    assert json.loads(call.kwargs["data"]) == {"NextToken": "page-2"}
    headers = call.kwargs["headers"]
    assert headers["X-Amz-Target"] == "StarlingDoveService.DescribeConfigRules"
    assert headers["Content-Type"] == "application/x-amz-json-1.1"
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/")
    assert f"/{signing_region}/config/aws4_request" in headers["Authorization"]
    assert "x-amz-target" in headers["Authorization"]
    assert headers["X-Amz-Date"]
    assert headers.get("X-Amz-Security-Token") == token
    assert call.kwargs["allow_redirects"] is False
    assert call.kwargs["timeout"] == 60
    assert "example-secret" in factory.call_args.kwargs["redact_values"]
    if token:
        assert token in factory.call_args.kwargs["redact_values"]
    retry_policy = factory.call_args.kwargs["retry"]
    assert retry_policy.is_retry("POST", 503)
    assert retry_policy.is_retry("POST", 429)
    assert not retry_policy.is_retry("POST", 400)


@pytest.mark.parametrize(
    "endpoint,result_key,operation,item,expected_key,limit",
    [
        (
            "resources",
            "Results",
            "SelectResourceConfig",
            '{"accountId":"111111111111","awsRegion":"eu-west-1","resourceType":"AWS::EC2::Instance","resourceId":"i-example","configuration":{"state":{"name":"running"}},"configurationItemCaptureTime":"2025-01-01T00:00:00Z"}',
            "resource_id",
            100,
        ),
        (
            "config_rules",
            "ConfigRules",
            "DescribeConfigRules",
            {"ConfigRuleArn": "arn:example:rule"},
            "config_rule_arn",
            None,
        ),
        (
            "rule_compliance",
            "ComplianceByConfigRules",
            "DescribeComplianceByConfigRule",
            {"ConfigRuleName": "example-rule", "Compliance": {"ComplianceType": "NON_COMPLIANT"}},
            "config_rule_name",
            None,
        ),
        (
            "conformance_packs",
            "ConformancePackDetails",
            "DescribeConformancePacks",
            {"ConformancePackArn": "arn:example:pack", "LastUpdateRequestedTime": 1735689600},
            "conformance_pack_arn",
            20,
        ),
    ],
)
def test_full_refresh_paginates_through_empty_and_terminal_pages(
    session: MagicMock, endpoint: str, result_key: str, operation: str, item: Any, expected_key: str, limit: int | None
) -> None:
    session.post.side_effect = [
        make_response({result_key: [item], "NextToken": "second"}),
        make_response({result_key: [], "NextToken": "third"}),
        make_response({result_key: [item]}),
    ]
    manager = make_manager()
    response = aws_config_source(make_config(), endpoint, "2014-11-12", manager)
    batches = list(cast(Iterable[Any], response.items()))

    assert len(batches) == 2
    assert all(expected_key in batch[0] for batch in batches)
    assert all(batch[0]["region"] == "eu-west-1" for batch in batches)
    assert all(key in batches[0][0] for key in response.primary_keys or [])
    if endpoint == "resources":
        assert batches[0][0]["configuration"] == {"state": {"name": "running"}}
        assert batches[0][0]["configuration_item_capture_time"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    if endpoint == "conformance_packs":
        assert batches[0][0]["last_update_requested_time"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    if endpoint == "rule_compliance":
        assert batches[0][0]["compliance"] == {"ComplianceType": "NON_COMPLIANT"}
    for call, token in zip(session.post.call_args_list, [None, "second", "third"], strict=True):
        payload = json.loads(call.kwargs["data"])
        expected: dict[str, Any] = {}
        if limit is not None:
            expected["Limit"] = limit
        if endpoint == "resources":
            expected["Expression"] = (
                "SELECT accountId, awsRegion, arn, resourceId, resourceType, resourceName, "
                "configuration, configurationItemCaptureTime, resourceCreationTime, tags"
            )
        if token:
            expected["NextToken"] = token
        assert payload == expected
        assert call.kwargs["headers"]["X-Amz-Target"] == f"StarlingDoveService.{operation}"
    assert [call.args[0] for call in manager.save_state.call_args_list] == [
        AwsConfigResumeConfig(next_token="second"),
        AwsConfigResumeConfig(next_token="third"),
        AwsConfigResumeConfig(complete=True),
    ]
    assert manager.safe_point.call_count == 3
    manager.clear_state.assert_called_once()
    session.close.assert_called_once()


def test_expired_resume_token_clears_state_and_fails_attempt(session: MagicMock) -> None:
    session.post.return_value = make_response({"__type": "InvalidNextTokenException"}, 400)
    manager = make_manager(AwsConfigResumeConfig(next_token="expired-token"))
    response = aws_config_source(make_config(), "config_rules", "2014-11-12", manager)

    with pytest.raises(AwsConfigError, match="InvalidNextTokenException"):
        list(cast(Iterable[Any], response.items()))

    assert json.loads(session.post.call_args.kwargs["data"]) == {"NextToken": "expired-token"}
    manager.clear_state.assert_called_once()
    session.close.assert_called_once()


def test_checkpoint_is_staged_before_yield_and_session_closes_on_interruption(session: MagicMock) -> None:
    session.post.return_value = make_response(
        {"ConfigRules": [{"ConfigRuleArn": "arn:example:rule"}], "NextToken": "next"}
    )
    manager = make_manager()
    rows = aws_config.get_rows(make_config(), aws_config.AWS_CONFIG_ENDPOINTS["config_rules"], "2014-11-12", manager)
    next(rows)
    manager.save_state.assert_called_once_with(AwsConfigResumeConfig(next_token="next"))
    manager.safe_point.assert_not_called()
    rows.close()
    session.close.assert_called_once()
    manager.clear_state.assert_not_called()


def test_completed_resume_does_not_repeat_requests(session: MagicMock) -> None:
    manager = make_manager(AwsConfigResumeConfig(complete=True))
    response = aws_config_source(make_config(), "config_rules", "2014-11-12", manager)

    assert list(cast(Iterable[Any], response.items())) == []
    manager.clear_state.assert_called_once()
    session.post.assert_not_called()


@pytest.mark.parametrize("token", ["saved-token", 123])
def test_invalid_page_token_does_not_advance_checkpoint(session: MagicMock, token: Any) -> None:
    session.post.return_value = make_response({"ConfigRules": [], "NextToken": token})
    manager = make_manager(AwsConfigResumeConfig(next_token="saved-token"))
    with pytest.raises(ValueError, match="invalid page token"):
        list(cast(Iterable[Any], aws_config_source(make_config(), "config_rules", "2014-11-12", manager).items()))
    manager.save_state.assert_not_called()
    session.close.assert_called_once()


@pytest.mark.parametrize("body", [{"Results": ["not JSON"]}, {"Results": ["[]"]}, []])
def test_malformed_results_do_not_advance_checkpoint(session: MagicMock, body: Any) -> None:
    session.post.return_value = make_response(body)
    manager = make_manager()
    with pytest.raises(ValueError):
        list(cast(Iterable[Any], aws_config_source(make_config(), "resources", "2014-11-12", manager).items()))
    manager.save_state.assert_not_called()
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "status,body,headers,code,throttled",
    [
        (400, {"__type": "com.amazonaws.config#ThrottlingException"}, {}, "ThrottlingException", True),
        (400, {"code": "Throttling"}, {}, "Throttling", True),
        (429, {"__type": "ThrottlingException"}, {}, "ThrottlingException", False),
        (503, {"__type": "ServiceUnavailableException"}, {}, "ServiceUnavailableException", False),
        (
            403,
            {"Message": "Denied"},
            {"x-amzn-ErrorType": "AccessDeniedException:http"},
            "AccessDeniedException",
            False,
        ),
        (400, {"__type": "UnrecognizedClientException"}, {}, "UnrecognizedClientException", False),
        (502, [], {}, "HTTP 502", False),
    ],
)
def test_error_classification(status: int, body: Any, headers: dict[str, str], code: str, throttled: bool) -> None:
    error = aws_config.error_for_response(make_response(body, status, headers))
    assert error.code == code
    assert isinstance(error, AwsConfigThrottledError) is throttled


def test_body_throttles_retry_without_sleep(session: MagicMock) -> None:
    session.post.side_effect = [
        make_response({"__type": "ThrottlingException", "message": "Rate exceeded"}, 400),
        make_response({"ConfigRules": []}),
    ]
    client = AwsConfigClient(make_config(), "2014-11-12")
    with patch.object(AwsConfigClient.request.retry, "wait", wait_none()):  # type: ignore[attr-defined]
        assert client.request("DescribeConfigRules", {}) == {"ConfigRules": []}
    assert session.post.call_count == 2


@pytest.mark.parametrize("schema_name", [None, "config_rules"])
@pytest.mark.parametrize("code", ["AccessDenied", "AccessDeniedException"])
def test_access_denied_only_blocks_selected_table(session: MagicMock, schema_name: str | None, code: str) -> None:
    session.post.return_value = make_response({"__type": code, "message": "Access denied"}, 400)
    valid, reason = validate_credentials(make_config(), "2014-11-12", schema_name)
    assert valid is (schema_name is None)
    assert reason is None if schema_name is None else "config:DescribeConfigRules" in (reason or "")
    session.post.assert_called_once()
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "code,message",
    [
        ("UnrecognizedClientException", "Check the access key ID"),
        ("InvalidSignatureException", "Check the secret access key"),
        ("ExpiredTokenException", "expired"),
        ("OptInRequired", "Enable AWS Config"),
        ("SubscriptionRequiredException", "Enable AWS Config"),
        ("InternalError", "try again"),
    ],
)
def test_credential_errors_are_actionable(session: MagicMock, code: str, message: str) -> None:
    session.post.return_value = make_response({"__type": code, "message": "Vendor error"}, 400)
    valid, reason = validate_credentials(make_config(), "2014-11-12")
    assert not valid
    assert message in (reason or "")
    session.post.assert_called_once()


@pytest.mark.parametrize(
    "schema,operation,limit",
    [
        (None, "DescribeConfigRules", None),
        ("resources", "SelectResourceConfig", 1),
        ("conformance_packs", "DescribeConformancePacks", 1),
    ],
)
def test_credential_probe_is_one_request(
    session: MagicMock, schema: str | None, operation: str, limit: int | None
) -> None:
    assert validate_credentials(make_config(), "2014-11-12", schema) == (True, None)
    session.post.assert_called_once()
    call = session.post.call_args
    assert call.kwargs["headers"]["X-Amz-Target"] == f"StarlingDoveService.{operation}"
    assert json.loads(call.kwargs["data"]).get("Limit") == limit


@pytest.mark.parametrize("region", ["https://example.com", "us-east-1.example.com/path", "us-east-1\n", "../us-east-1"])
def test_invalid_region_fails_before_transport(session: MagicMock, region: str) -> None:
    valid, reason = validate_credentials(make_config(region=region), "2014-11-12")
    assert not valid
    assert reason == "Enter an AWS region such as us-east-1."
    session.post.assert_not_called()


@pytest.mark.parametrize("field", ["aws_access_key_id", "aws_secret_access_key"])
def test_missing_credentials_fail_before_transport(session: MagicMock, field: str) -> None:
    valid, reason = validate_credentials(make_config(**{field: ""}), "2014-11-12")
    assert not valid
    assert "Enter both" in (reason or "")
    session.post.assert_not_called()


def test_unknown_table_and_version_fail_before_transport(session: MagicMock) -> None:
    assert validate_credentials(make_config(), "2014-11-12", "unknown") == (False, "Unknown AWS Config table: unknown")
    with pytest.raises(ValueError, match="Unknown AWS Config table"):
        aws_config_source(make_config(), "unknown", "2014-11-12", make_manager())
    valid, reason = validate_credentials(make_config(), "invalid-version")
    assert not valid
    assert "Unsupported AWS Config API version" in (reason or "")
    session.post.assert_not_called()


def test_network_failure_closes_probe_session(session: MagicMock) -> None:
    session.post.side_effect = requests.Timeout()
    valid, reason = validate_credentials(make_config(), "2014-11-12")
    assert not valid
    assert "try again" in (reason or "")
    session.close.assert_called_once()


def test_new_invalid_token_is_not_silently_restarted(session: MagicMock) -> None:
    session.post.return_value = make_response({"__type": "InvalidNextTokenException"}, 400)
    with pytest.raises(AwsConfigError, match="InvalidNextTokenException"):
        list(
            cast(
                Iterable[Any],
                aws_config_source(make_config(), "config_rules", "2014-11-12", make_manager()).items(),
            )
        )
    session.post.assert_called_once()
