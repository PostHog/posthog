import json
import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

import requests
from botocore.session import Session

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_security_hub import aws_security_hub
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_security_hub.aws_security_hub import (
    AwsSecurityHubClient,
    AwsSecurityHubError,
    AwsSecurityHubResumeConfig,
    aws_security_hub_source,
    probe_endpoint_permissions,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_security_hub.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_security_hub.source import (
    AwsSecurityHubSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssecurityhub import (
    AwsSecurityHubSourceConfig,
)

VERSION = "2018-10-26"
SUBSCRIPTION_A = "arn:aws:securityhub:eu-west-1:111111111111:subscription/example-standard/v/1.0.0"
SUBSCRIPTION_B = "arn:aws:securityhub:eu-west-1:111111111111:subscription/other-standard/v/2.0.0"


def controls_path(subscription_arn: str) -> str:
    return "/standards/controls/" + subscription_arn.replace(":", "%3A")


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


def driver() -> SourceDriver:
    return SourceDriver(AwsSecurityHubSource(), config())


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
def test_signed_rest_requests(operation: str, method: str, path: str) -> None:
    payload = {"MaxResults": 100, "NextToken": "example/+="}
    redirect = ScriptedResponse(status=302, json={}, headers={"Location": "https://example.com/redirect"})
    with scripted_network([redirect]) as network:
        AwsSecurityHubClient(config(), VERSION).request(operation, payload)
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.method == method
    assert request.origin == "https://securityhub.eu-west-1.amazonaws.com"
    assert request.path == path
    if method == "GET":
        assert request.query == {"MaxResults": ("100",), "NextToken": ("example/+=",)}
        assert request.body is None
    else:
        assert request.json() == payload
        assert request.headers["content-type"] == "application/json"
    headers = request.headers
    assert "x-amz-target" not in headers
    assert headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/")
    assert "/eu-west-1/securityhub/aws4_request" in headers["authorization"]
    assert headers["x-amz-security-token"] == "fake-session-token"
    assert headers["x-amz-date"]


@pytest.mark.parametrize("region,suffix", [("us-east-1", "amazonaws.com"), ("cn-north-1", "amazonaws.com.cn")])
def test_region_and_long_lived_credentials(region: str, suffix: str) -> None:
    with scripted_network([ScriptedResponse(json={})]) as network:
        AwsSecurityHubClient(config(region, token=None), VERSION).request("GetInsights", {"MaxResults": 1})
    request = network.requests_log[0]
    assert request.url == f"https://securityhub.{region}.{suffix}/insights/get"
    assert "x-amz-security-token" not in request.headers


@pytest.mark.parametrize("region", ["us-east-1.example.com", "us-east-1/path", "", "https://example.com"])
def test_invalid_region_never_sends_credentials(region: str) -> None:
    with scripted_network([]) as network:
        success, message = validate_credentials(config(region), VERSION)
    assert not success
    assert message and "valid AWS region" in message
    assert network.requests_log == []


def test_unsupported_version_never_sends_request() -> None:
    with scripted_network([]) as network:
        with pytest.raises(ValueError, match="Unsupported AWS Security Hub API version"):
            AwsSecurityHubClient(config(), "2099-01-01")
    assert network.requests_log == []


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
    endpoint: str, result_key: str, incremental: bool, watermark: object, expected_start: str | None
) -> None:
    result = driver().run(
        endpoint,
        [ScriptedResponse(json={result_key: []})],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )
    assert result.raised is None
    assert result.rows == []
    request = result.requests[0]
    payload = request.json() if request.body else {key: list(values) for key, values in request.query.items()}
    if expected_start:
        assert payload["Filters"] == {"UpdatedAt": [{"Start": expected_start}]}
    else:
        assert "Filters" not in payload
    if endpoint == "findings":
        assert payload["SortCriteria"] == [{"Field": "UpdatedAt", "SortOrder": "asc"}]
    else:
        assert "SortCriteria" not in payload


@pytest.mark.parametrize("finished", [False, True])
def test_resume_preserves_original_filter_and_completion(finished: bool) -> None:
    state = AwsSecurityHubResumeConfig(next_token="saved", updated_after="2025-01-01T00:00:00+00:00", finished=finished)
    result = driver().run(
        "findings",
        [] if finished else [ScriptedResponse(json={"Findings": [{"Id": "remaining"}]})],
        resume_state=state,
        should_use_incremental_field=True,
        db_incremental_field_last_value="2025-02-01T00:00:00Z",
    )
    assert result.raised is None
    if finished:
        assert result.items == []
        assert result.requests == []
    else:
        assert result.items == [[{"id": "remaining"}]]
        payload = result.requests[0].json()
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
def test_error_mapping(status: int, body: object, header: str | None, code: str, permanent: bool) -> None:
    answer = ScriptedResponse(status=status, json=body, headers={"x-amzn-ErrorType": header} if header else {})
    result = driver().run("findings", always(answer))
    assert isinstance(result.raised, AwsSecurityHubError)
    assert result.raised.code == code
    errors = AwsSecurityHubSource().get_non_retryable_errors()
    assert any(pattern in str(result.raised) for pattern in errors) is permanent


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
def test_permission_probes_do_not_hide_tables_on_transient_errors(failure: Exception) -> None:
    if isinstance(failure, AwsSecurityHubError):
        script = always(ScriptedResponse(status=500, json={"__type": failure.code, "message": failure.message}))
    else:
        script = always(failure)
    with scripted_network(script) as network:
        assert probe_endpoint_permissions(config(), VERSION, ["findings"]) == {"findings": None}
    assert network.requests_log
    assert {request.path for request in network.requests_log} == {"/findings"}


DENIED = ScriptedResponse(status=403, json={}, headers={"x-amzn-ErrorType": "AccessDeniedException"})
ONE_SUBSCRIPTION = ScriptedResponse(json={"StandardsSubscriptions": [{"StandardsSubscriptionArn": SUBSCRIPTION_A}]})


@pytest.mark.parametrize(
    "endpoint,script,missing,paths",
    [
        ("enabled_standards", [DENIED], "GetEnabledStandards", ["/standards/get"]),
        (
            "standards_controls",
            [ONE_SUBSCRIPTION, DENIED],
            "DescribeStandardsControls",
            ["/standards/get", controls_path(SUBSCRIPTION_A)],
        ),
        ("standards_controls", [DENIED], "GetEnabledStandards", ["/standards/get"]),
        ("standards_controls", [ScriptedResponse(json={"StandardsSubscriptions": []})], None, ["/standards/get"]),
    ],
)
def test_permission_probe_names_missing_permission(
    endpoint: str, script: list[ScriptedResponse], missing: str | None, paths: list[str]
) -> None:
    with scripted_network(script) as network:
        permissions = probe_endpoint_permissions(config(), VERSION, [endpoint])
    if missing:
        assert f"securityhub:{missing}" in (permissions[endpoint] or "")
    else:
        assert permissions[endpoint] is None
    assert [request.path for request in network.requests_log] == paths


def test_standards_controls_fan_out_over_enabled_standards() -> None:
    script = route(
        {
            "/standards/get": [
                ScriptedResponse(
                    json={"StandardsSubscriptions": [{"StandardsSubscriptionArn": SUBSCRIPTION_B}], "NextToken": "p2"}
                ),
                ONE_SUBSCRIPTION,
            ],
            controls_path(SUBSCRIPTION_A): [
                ScriptedResponse(json={"Controls": [{"StandardsControlArn": "control-a1"}], "NextToken": "c2"}),
                ScriptedResponse(json={"Controls": [{"StandardsControlArn": "control-a2"}]}),
            ],
            controls_path(SUBSCRIPTION_B): [
                ScriptedResponse(
                    json={
                        "Controls": [
                            {"StandardsControlArn": "control-b1", "ControlStatusUpdatedAt": "2025-01-01T00:00:00Z"}
                        ]
                    }
                )
            ],
        }
    )
    result = driver().run("standards_controls", script)
    assert result.raised is None
    assert result.rows == [
        {"standards_subscription_arn": SUBSCRIPTION_A, "standards_control_arn": "control-a1"},
        {"standards_subscription_arn": SUBSCRIPTION_A, "standards_control_arn": "control-a2"},
        {
            "standards_subscription_arn": SUBSCRIPTION_B,
            "standards_control_arn": "control-b1",
            "control_status_updated_at": dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
        },
    ]
    assert [(request.path, request.param("NextToken")) for request in result.requests] == [
        ("/standards/get", None),
        ("/standards/get", None),
        (controls_path(SUBSCRIPTION_A), None),
        (controls_path(SUBSCRIPTION_A), "c2"),
        (controls_path(SUBSCRIPTION_B), None),
    ]
    assert result.requests[1].json()["NextToken"] == "p2"
    assert [(state.parent_id, state.next_token, state.finished) for state in result.saved_states] == [
        (SUBSCRIPTION_A, "c2", False),
        (SUBSCRIPTION_B, None, False),
        (None, None, True),
    ]


@pytest.mark.parametrize("next_token", ["saved", None])
def test_standards_controls_resume_skips_finished_subscriptions(next_token: str | None) -> None:
    script = route(
        {
            "/standards/get": [
                ScriptedResponse(
                    json={
                        "StandardsSubscriptions": [
                            {"StandardsSubscriptionArn": SUBSCRIPTION_A},
                            {"StandardsSubscriptionArn": SUBSCRIPTION_B},
                        ]
                    }
                )
            ],
            controls_path(SUBSCRIPTION_B): [
                ScriptedResponse(json={"Controls": [{"StandardsControlArn": "control-b"}]})
            ],
        }
    )
    state = AwsSecurityHubResumeConfig(next_token=next_token, parent_id=SUBSCRIPTION_B)
    result = driver().run("standards_controls", script, resume_state=state)
    assert result.raised is None
    assert result.rows == [{"standards_subscription_arn": SUBSCRIPTION_B, "standards_control_arn": "control-b"}]
    assert result.requests[-1].path == controls_path(SUBSCRIPTION_B)
    assert result.requests[-1].param("NextToken") == next_token


@pytest.mark.parametrize("endpoint", ["security_control_definitions", "products", "members"])
def test_page_size_stays_within_vendor_limit(endpoint: str) -> None:
    endpoint_config = ENDPOINTS[endpoint]
    result = driver().run(endpoint, [ScriptedResponse(json={endpoint_config.result_key: []})])
    assert result.raised is None
    request = result.requests[0]
    model = Session().get_service_model("securityhub", api_version=VERSION)
    input_shape = model.operation_model(endpoint_config.operation).input_shape
    assert input_shape is not None
    limit = input_shape.members["MaxResults"].metadata["max"]
    assert 0 < int(request.param("MaxResults") or 0) <= limit
    if endpoint == "members":
        assert request.param("OnlyAssociated") == "false"


def test_finding_identity_and_timestamps_survive_normalization() -> None:
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
    result = driver().run(
        "findings",
        [
            ScriptedResponse(
                json={
                    "Findings": [
                        finding,
                        {**finding, "ProductArn": "arn:aws:securityhub:eu-west-1::product/example/product-two"},
                        {**finding, "AwsAccountId": "222222222222"},
                        {**finding, "Region": "us-east-1"},
                    ]
                }
            )
        ],
        should_use_incremental_field=True,
    )
    assert result.raised is None
    assert result.response is not None
    assert result.response.primary_keys
    assert len({tuple(row[key] for key in result.response.primary_keys) for row in result.rows}) == 4
    assert result.rows[0]["resources"] == finding["Resources"]
    assert result.rows[0]["severity"] == finding["Severity"]
    assert result.response.partition_keys
    assert result.rows[0][result.response.partition_keys[0]] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    assert result.rows[0]["updated_at"] == dt.datetime(2025, 2, 1, tzinfo=dt.UTC)


@pytest.mark.parametrize("missing_field", ["aws_access_key_id", "aws_secret_access_key"])
def test_missing_credentials_do_not_send_request(missing_field: str) -> None:
    source_config = config()
    setattr(source_config, missing_field, "")
    with scripted_network([]) as network:
        valid, message = validate_credentials(source_config, VERSION)
    assert not valid
    assert message == "Enter both an AWS access key ID and a secret access key."
    assert network.requests_log == []


def test_unknown_schema_does_not_send_request() -> None:
    with scripted_network([]) as network:
        valid, message = validate_credentials(config(), VERSION, "unknown")
    assert not valid
    assert message == "Unknown AWS Security Hub table: unknown"
    assert network.requests_log == []


def test_validation_network_error(session: Mock) -> None:
    session.request.side_effect = requests.Timeout()
    assert validate_credentials(config(), VERSION) == (False, "Could not reach AWS Security Hub. Try again.")
    session.close.assert_called_once()
