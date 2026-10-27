import json
from collections.abc import Generator, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
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


def driver() -> SourceDriver:
    return SourceDriver(AwsWafSource(), config())


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
def test_resume_from_checkpoint(marker: str | None) -> None:
    result = driver().run(
        "web_acls",
        [ScriptedResponse(json={"WebACLs": []})],
        resume_state=AwsWafResumeConfig(next_marker=marker),
    )
    assert result.raised is None
    assert result.items == []
    payload = result.requests[0].json()
    if marker:
        assert payload["NextMarker"] == marker
    else:
        assert "NextMarker" not in payload
    assert result.saved_states == [AwsWafResumeConfig()]
    assert result.committed_states == [AwsWafResumeConfig()]


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


def test_repeated_marker_fails_without_advancing_checkpoint() -> None:
    saved = AwsWafResumeConfig(next_marker="saved")
    result = driver().run(
        "web_acls",
        [ScriptedResponse(json={"WebACLs": [], "NextMarker": "saved"})],
        resume_state=saved,
    )
    assert isinstance(result.raised, ValueError)
    assert "repeated pagination marker" in str(result.raised)
    assert result.saved_states == []
    assert result.final_state == saved


@pytest.mark.parametrize(
    "schema,expected_reason",
    [
        (None, None),
        ("ip_sets", "Grant wafv2:ListIPSets and wafv2:GetIPSet for this table."),
        (
            "sampled_requests",
            "Grant wafv2:ListWebACLs, wafv2:GetWebACL and wafv2:GetSampledRequests for this table.",
        ),
        ("request_metrics", "Grant cloudwatch:ListMetrics and cloudwatch:GetMetricData for this table."),
    ],
)
@pytest.mark.parametrize("code", ["AccessDenied", "AccessDeniedException", "WAFUnauthorizedOperationException"])
def test_missing_permissions_at_creation_or_schema_probe(
    schema: str | None, expected_reason: str | None, code: str
) -> None:
    with scripted_network([ScriptedResponse(status=400, json={"__type": f"com.amazonaws.wafv2#{code}"})]) as network:
        valid, reason = validate_credentials(config(), schema)
    assert valid is (schema is None)
    assert reason == expected_reason
    assert len(network.requests_log) == 1


def test_schema_probe_checks_detail_permission() -> None:
    with scripted_network(
        [
            ScriptedResponse(json={"IPSets": [{"Id": "id", "Name": "example"}]}),
            ScriptedResponse(status=400, json={"__type": "AccessDeniedException"}),
        ]
    ) as network:
        valid, reason = validate_credentials(config(), "ip_sets")
    assert not valid
    assert reason and "wafv2:GetIPSet" in reason
    assert network.requests_log[-1].json() == {"Scope": "REGIONAL", "Id": "id", "Name": "example"}


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
def test_credential_errors_are_actionable_and_non_retryable(code: str, expected: str) -> None:
    error_response = response({"__type": code, "Message": "AWS rejected this request."}, 400)
    with scripted_network(
        [ScriptedResponse(status=400, json={"__type": code, "Message": "AWS rejected this request."})]
    ) as network:
        valid, reason = validate_credentials(config())
    assert not valid and reason and expected in reason
    error = error_for_response(error_response)
    mapped = [
        message for pattern, message in AwsWafSource().get_non_retryable_errors().items() if pattern in str(error)
    ]
    assert mapped and all(message and expected in message for message in mapped)
    assert len(network.requests_log) == 1


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
def test_transient_errors_retry_without_transport_retry(status: int, code: str) -> None:
    with scripted_network(
        [ScriptedResponse(status=status, json={"__type": code}), ScriptedResponse(json={"WebACLs": []})]
    ) as network:
        client = AwsWafClient(config())
        assert client.request("ListWebACLs", {"Scope": "REGIONAL", "Limit": 1}) == {"WebACLs": []}
        client.close()
    assert len(network.requests_log) == 2


def test_retries_stop_after_five_attempts() -> None:
    with scripted_network(always(ScriptedResponse(status=400, json={"__type": "ThrottlingException"}))) as network:
        client = AwsWafClient(config())
        with pytest.raises(AwsWafRetryableError, match="ThrottlingException"):
            client.request("ListWebACLs", {"Scope": "REGIONAL", "Limit": 1})
        client.close()
    assert len(network.requests_log) == 5


@pytest.mark.parametrize("schema,capture", [(None, True), ("sampled_requests", False)])
def test_tracked_transport_redacts_secrets_and_disables_nested_retries(schema: str | None, capture: bool) -> None:
    with scripted_network([ScriptedResponse(json={"WebACLs": []})]) as network:
        assert validate_credentials(config(), schema) == (True, None)
    assert network.session_options[0]["retry"].total == 0
    assert set(network.session_options[0]["redact_values"]) == {"example-secret", "example-token"}
    assert network.session_options[0]["capture"] is capture


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
def test_invalid_configuration_does_not_send_credentials(overrides: dict[str, str], expected: str) -> None:
    with scripted_network([]) as network:
        valid, reason = validate_credentials(config(**overrides))
    assert not valid and reason and expected in reason
    assert network.requests_log == []


def test_unknown_schema_and_api_version_fail_before_requests() -> None:
    with scripted_network([]) as network:
        assert validate_credentials(config(), "unknown") == (False, "Unknown AWS WAF table: unknown")
        valid, reason = validate_credentials(config(), api_version="2015-08-24")
    assert not valid and reason and "Unsupported AWS WAF API version" in reason
    result = driver().run("unknown", [])
    assert isinstance(result.raised, ValueError)
    assert "Unknown AWS WAF table" in str(result.raised)
    assert network.requests_log == []
    assert result.requests == []


NOW = datetime(2026, 10, 16, 12, 30, tzinfo=UTC)


def targets(session: MagicMock) -> list[str]:
    return [call.kwargs["headers"]["X-Amz-Target"].split(".")[-1] for call in session.post.call_args_list]


def payloads(session: MagicMock) -> list[dict[str, Any]]:
    return [json.loads(call.kwargs["data"]) for call in session.post.call_args_list]


def rows_for(table: str, **kwargs: Any) -> list[dict[str, Any]]:
    with patch(f"{MODULE}.utc_now", return_value=NOW):
        stream = aws_waf_source(config(**kwargs.pop("overrides", {})), table, manager(), **kwargs)
        return [row for batch in cast(Iterable[list[dict[str, Any]]], stream.items()) for row in batch]


def test_managed_rule_groups_merge_summary_and_description(session: MagicMock) -> None:
    summary = {"VendorName": "AWS", "Name": "AWSManagedRulesCommonRuleSet", "VersioningSupported": True}
    session.post.side_effect = [
        response({"ManagedRuleGroups": [summary]}),
        response({"VersionName": "Version_1.0", "Capacity": 700, "Rules": [{"Name": "NoUserAgent_HEADER"}]}),
    ]
    rows = rows_for("managed_rule_groups")
    assert targets(session) == ["ListAvailableManagedRuleGroups", "DescribeManagedRuleGroup"]
    assert payloads(session)[1] == {"Scope": "REGIONAL", "VendorName": "AWS", "Name": "AWSManagedRulesCommonRuleSet"}
    assert rows == [
        {
            "vendor_name": "AWS",
            "name": "AWSManagedRulesCommonRuleSet",
            "versioning_supported": True,
            "version_name": "Version_1.0",
            "capacity": 700,
            "rules": [{"Name": "NoUserAgent_HEADER"}],
            "region": "eu-west-1",
            "scope": "REGIONAL",
        }
    ]


@pytest.mark.parametrize("scope", ["REGIONAL", "CLOUDFRONT"])
def test_protected_resources_cover_every_resource_type(session: MagicMock, scope: str) -> None:
    web_acl = {"ARN": "arn:aws:wafv2:eu-west-1:123456789012:regional/webacl/main/id", "Id": "id", "Name": "main"}
    alb_arn = "arn:aws:elasticloadbalancing:eu-west-1:123456789012:loadbalancer/app/example/1"
    responses = {
        "ListWebACLs": response({"WebACLs": [web_acl]}),
        "APPLICATION_LOAD_BALANCER": response({"ResourceArns": [alb_arn]}),
        "AGENTCORE_GATEWAY": response({"__type": "WAFInvalidParameterException"}, 400),
    }

    def post(*args: Any, **kwargs: Any) -> requests.Response:
        payload = json.loads(kwargs["data"])
        key = payload.get("ResourceType") or kwargs["headers"]["X-Amz-Target"].split(".")[-1]
        return responses.get(key, response({"ResourceArns": []}))

    session.post.side_effect = post
    rows = rows_for("protected_resources", overrides={"scope": scope})
    if scope == "CLOUDFRONT":
        assert rows == []
        session.post.assert_not_called()
        return
    assert [payload.get("ResourceType") for payload in payloads(session)[1:]] == [
        "APPLICATION_LOAD_BALANCER",
        "API_GATEWAY",
        "APPSYNC",
        "COGNITO_USER_POOL",
        "APP_RUNNER_SERVICE",
        "VERIFIED_ACCESS_INSTANCE",
        "AMPLIFY",
        "AGENTCORE_GATEWAY",
    ]
    assert rows == [
        {
            "web_acl_arn": web_acl["ARN"],
            "web_acl_id": "id",
            "web_acl_name": "main",
            "resource_type": "APPLICATION_LOAD_BALANCER",
            "resource_arn": alb_arn,
            "region": "eu-west-1",
            "scope": "REGIONAL",
        }
    ]


@pytest.mark.parametrize(
    "last_value,expected_start",
    [
        (None, NOW - timedelta(hours=3)),
        (NOW - timedelta(hours=5), NOW - timedelta(hours=3)),
        ((NOW - timedelta(minutes=20)).isoformat(), NOW - timedelta(minutes=20)),
    ],
)
def test_sampled_requests_window_rules_and_header_redaction(
    session: MagicMock, last_value: Any, expected_start: datetime
) -> None:
    web_acl = {
        "ARN": "arn:aws:wafv2:eu-west-1:123456789012:regional/webacl/main/id",
        "Id": "id",
        "Name": "main",
        "Rules": [
            {"Name": "sampled", "VisibilityConfig": {"MetricName": "sampled-rule", "SampledRequestsEnabled": True}},
            {"Name": "unsampled", "VisibilityConfig": {"MetricName": "quiet-rule", "SampledRequestsEnabled": False}},
        ],
    }
    sample = {
        "Request": {
            "ClientIP": "192.0.2.10",
            "Country": "DE",
            "URI": "/login",
            "Method": "POST",
            "HTTPVersion": "HTTP/2.0",
            "Headers": [{"Name": "Cookie", "Value": "session=fake"}, {"Name": "User-Agent", "Value": "curl"}],
        },
        "Weight": 2,
        "Timestamp": (NOW - timedelta(minutes=5)).timestamp(),
        "Action": "BLOCK",
    }
    session.post.side_effect = [
        response({"WebACLs": [{"Id": "id", "Name": "main", "ARN": web_acl["ARN"]}]}),
        response({"WebACL": web_acl}),
        response(
            {
                "SampledRequests": [sample],
                "PopulationSize": 40,
                "TimeWindow": {
                    "StartTime": expected_start.timestamp(),
                    "EndTime": (NOW - timedelta(minutes=2)).timestamp(),
                },
            }
        ),
        response({"SampledRequests": [], "TimeWindow": {"EndTime": NOW.timestamp()}}),
    ]
    rows = rows_for("sampled_requests", incremental_last_value=last_value)
    assert targets(session) == ["ListWebACLs", "GetWebACL", "GetSampledRequests", "GetSampledRequests"]
    assert payloads(session)[3]["TimeWindow"] == {
        "StartTime": (NOW - timedelta(minutes=2)).timestamp(),
        "EndTime": NOW.timestamp(),
    }
    assert payloads(session)[2] == {
        "WebAclArn": web_acl["ARN"],
        "RuleMetricName": "sampled-rule",
        "Scope": "REGIONAL",
        "TimeWindow": {"StartTime": expected_start.timestamp(), "EndTime": NOW.timestamp()},
        "MaxItems": 500,
    }
    [row] = rows
    assert row["headers"] == [{"Name": "Cookie", "Value": "[REDACTED]"}, {"Name": "User-Agent", "Value": "curl"}]
    assert "session=fake" not in json.dumps(row, default=str)
    assert {key: row[key] for key in ("client_ip", "uri", "http_version", "action", "weight", "population_size")} == {
        "client_ip": "192.0.2.10",
        "uri": "/login",
        "http_version": "HTTP/2.0",
        "action": "BLOCK",
        "weight": 2,
        "population_size": 40,
    }
    assert row["timestamp"] == NOW - timedelta(minutes=5)
    assert row["rule_metric_name"] == "sampled-rule"
    assert len(row["id"]) == 64


@pytest.mark.parametrize("scope,region_filter", [("REGIONAL", True), ("CLOUDFRONT", False)])
def test_request_metrics_from_cloudwatch(session: MagicMock, scope: str, region_filter: bool) -> None:
    regional = {
        "Namespace": "AWS/WAFV2",
        "MetricName": "BlockedRequests",
        "Dimensions": [
            {"Name": "WebACL", "Value": "main"},
            {"Name": "Rule", "Value": "ALL"},
            {"Name": "Region", "Value": "us-east-1"},
        ],
    }
    cloudfront = {
        "Namespace": "AWS/WAFV2",
        "MetricName": "AllowedRequests",
        "Dimensions": [{"Name": "WebACL", "Value": "edge"}, {"Name": "Rule", "Value": "ALL"}],
    }
    hour = NOW.replace(minute=0) - timedelta(hours=1)
    session.post.side_effect = [
        response({"Metrics": [regional], "NextToken": "metrics-2"}),
        response({"Metrics": [cloudfront]}),
        response(
            {
                "MetricDataResults": [{"Id": "m0", "Timestamps": [hour.timestamp()], "Values": [5.0]}],
                "NextToken": "data-2",
            }
        ),
        response(
            {"MetricDataResults": [{"Id": "m0", "Timestamps": [NOW.replace(minute=0).timestamp()], "Values": [7.0]}]}
        ),
    ]
    rows = rows_for(
        "request_metrics",
        overrides={"scope": scope, "aws_region": "us-east-1"},
        incremental_last_value=hour + timedelta(minutes=10),
    )
    calls = session.post.call_args_list
    assert {call.args[0] for call in calls} == {"https://monitoring.us-east-1.amazonaws.com/"}
    assert "/us-east-1/monitoring/aws4_request" in calls[0].kwargs["headers"]["Authorization"]
    assert calls[0].kwargs["headers"]["Content-Type"] == "application/x-amz-json-1.0"
    assert [call.kwargs["headers"]["X-Amz-Target"] for call in calls] == [
        "GraniteServiceVersion20100801.ListMetrics",
        "GraniteServiceVersion20100801.ListMetrics",
        "GraniteServiceVersion20100801.GetMetricData",
        "GraniteServiceVersion20100801.GetMetricData",
    ]
    sent = payloads(session)
    assert ("Dimensions" in sent[0]) is region_filter
    assert sent[1]["NextToken"] == "metrics-2"
    expected_metric = regional if region_filter else cloudfront
    assert sent[2]["MetricDataQueries"] == [
        {"Id": "m0", "MetricStat": {"Metric": expected_metric, "Period": 3600, "Stat": "Sum"}, "ReturnData": True}
    ]
    assert sent[2]["StartTime"] == hour.timestamp()
    assert sent[3]["NextToken"] == "data-2"
    assert [(row["metric_id"], row["timestamp"], row["value"]) for row in rows] == [
        (
            "BlockedRequests|Region=us-east-1|Rule=ALL|WebACL=main"
            if region_filter
            else "AllowedRequests|Rule=ALL|WebACL=edge",
            timestamp,
            value,
        )
        for timestamp, value in [(hour, 5.0), (NOW.replace(minute=0), 7.0)]
    ]


def test_request_metrics_fail_on_a_failed_series(session: MagicMock) -> None:
    metric = {
        "Namespace": "AWS/WAFV2",
        "MetricName": "BlockedRequests",
        "Dimensions": [{"Name": "Region", "Value": "eu-west-1"}],
    }
    session.post.side_effect = [
        response({"Metrics": [metric]}),
        response({"MetricDataResults": [{"Id": "m0", "StatusCode": "InternalError", "Timestamps": [], "Values": []}]}),
    ]
    with pytest.raises(AwsWafRetryableError, match="InternalError"):
        rows_for("request_metrics")
