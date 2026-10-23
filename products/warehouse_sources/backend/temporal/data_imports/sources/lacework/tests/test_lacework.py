from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lacework import (
    LaceworkSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lacework.lacework import (
    INVALID_ACCOUNT_ERROR,
    LaceworkResumeConfig,
    LaceworkRetryableError,
    _is_same_host,
    base_url,
    normalize_account,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lacework.source import LaceworkSource


def _token() -> ScriptedResponse:
    return ScriptedResponse(status=201, json={"token": "tok-123", "expiresAt": "2100-01-01T00:00:00.000Z"})


def _run(endpoint: str, responses: list[ScriptedResponse], **inputs: Any) -> DriveResult:
    driver = SourceDriver(
        LaceworkSource(), LaceworkSourceConfig(account_name="mycompany", key_id="KEY_ID", secret_key="secret")
    )
    return driver.run(endpoint, [_token(), *responses], **inputs)


class TestAccountNormalization:
    @parameterized.expand(
        [
            ("bare_account", "mycompany"),
            ("full_domain", "mycompany.lacework.net"),
            ("full_url", "https://mycompany.lacework.net/"),
            ("url_with_path", "https://mycompany.lacework.net/api/v2"),
            ("whitespace", "  mycompany  "),
        ]
    )
    def test_normalize_account_variants(self, _name: str, value: str) -> None:
        assert normalize_account(value) == "mycompany"
        assert base_url(value) == "https://mycompany.lacework.net/api/v2"

    @parameterized.expand(
        [
            ("empty", ""),
            ("leading_dash", "-mycompany"),
            ("query_injection", "mycompany?x=1"),
            ("space_inside", "my company"),
            ("at_sign", "user@evil.com"),
        ]
    )
    def test_base_url_rejects_invalid_accounts(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError, match=INVALID_ACCOUNT_ERROR):
            base_url(value)


class TestIsSameHost:
    @parameterized.expand(
        [
            ("plain", "https://mycompany.lacework.net/api/v2/Alerts/next"),
            ("uppercase_host", "https://MyCompany.Lacework.NET/api/v2/next"),
            ("default_port", "https://mycompany.lacework.net:443/api/v2/next"),
        ]
    )
    def test_accepts_matching_host(self, _name: str, url: str) -> None:
        assert _is_same_host(url, "mycompany") is True

    @parameterized.expand(
        [
            ("foreign_host", "https://evil.com/api/v2/steal"),
            # requests/urllib3 treat a backslash in the authority as a path separator, so these
            # connect to evil.example while urlparse would otherwise report the trusted host.
            ("literal_backslash", "https://evil.example\\@mycompany.lacework.net/api/v2/next"),
            ("encoded_backslash_lower", "https://evil.example%5c@mycompany.lacework.net/api/v2/next"),
            ("encoded_backslash_upper", "https://evil.example%5C@mycompany.lacework.net/api/v2/next"),
            ("http_scheme", "http://mycompany.lacework.net/api/v2/next"),
            ("non_default_port", "https://mycompany.lacework.net:8443/api/v2/next"),
        ]
    )
    def test_rejects_bad_host(self, _name: str, url: str) -> None:
        assert _is_same_host(url, "mycompany") is False


class TestValidateCredentials:
    @parameterized.expand([("unauthorized", 401)])
    def test_bad_credentials(self, _name: str, status_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json={"message": "unauthorized"})]) as network:
            ok, message = validate_credentials("mycompany", "KEY_ID", "secret")

        assert ok is False
        assert message == "Invalid Lacework API key ID or secret key"
        assert network.requests_log[0].path == "/api/v2/access/tokens"

    def test_other_error_surfaces_api_message(self) -> None:
        with scripted_network([ScriptedResponse(status=400, json={"message": "expiryTime out of range"})]):
            ok, message = validate_credentials("mycompany", "KEY_ID", "secret")

        assert ok is False
        assert message == "expiryTime out of range"

    def test_invalid_account_fails_without_network(self) -> None:
        with scripted_network([]) as network:
            ok, message = validate_credentials("my company", "KEY_ID", "secret")

        assert ok is False
        assert message == INVALID_ACCOUNT_ERROR
        assert network.requests_log == []
        assert network.session_options == []


class TestGetRowsWindowing:
    @parameterized.expand(
        [
            (
                "compliance",
                "compliance_evaluations_aws",
                "/Configs/ComplianceEvaluations/search",
                "dataset",
                "AwsCompliance",
            ),
            ("inventory", "inventory_gcp", "/Inventory/search", "csp", "GCP"),
        ]
    )
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_search_includes_required_body_param(
        self, _name: str, endpoint: str, path: str, param: str, value: str
    ) -> None:
        result = _run(
            endpoint,
            [ScriptedResponse(json={"data": [], "paging": {}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[1].path == f"/api/v2{path}"
        assert result.requests[1].json()[param] == value

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_full_refresh_uses_default_lookback(self) -> None:
        # agent_info: 7-day lookback with 7-day windows -> exactly one request window.
        result = _run("agent_info", [ScriptedResponse(json={"data": [{"mid": 1}], "paging": {}})])

        assert result.raised is None
        assert result.rows == [{"mid": 1}]
        assert len(result.requests[1:]) == 1
        assert result.requests[1].json()["timeFilter"] == {
            "startTime": "2026-06-08T12:00:00.000Z",
            "endTime": "2026-06-15T12:00:00.000Z",
        }


class TestGetRowsUnwindowed:
    def test_list_endpoint_pages_without_time_range_and_strips_credentials(self) -> None:
        next_url = "https://mycompany.lacework.net/api/v2/CloudAccounts/page2"
        result = _run(
            "cloud_accounts",
            [
                ScriptedResponse(
                    json={
                        "data": [
                            {
                                "intgGuid": "A",
                                "data": {
                                    "awsAccountId": "123",
                                    "crossAccountCredentials": {"externalId": "x", "roleArn": "arn"},
                                },
                            }
                        ],
                        "paging": {"urls": {"nextPage": next_url}},
                    },
                ),
                ScriptedResponse(
                    json={"data": [{"intgGuid": "B", "data": {"credentials": {"clientSecret": "s"}, "tenantId": "t"}}]},
                ),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"intgGuid": "A", "data": {"awsAccountId": "123"}},
            {"intgGuid": "B", "data": {"tenantId": "t"}},
        ]
        assert [(request.method, request.url, request.body) for request in result.requests[1:]] == [
            ("GET", "https://mycompany.lacework.net/api/v2/CloudAccounts", None),
            ("GET", next_url, None),
        ]
        assert result.saved_states == []

    @parameterized.expand(
        [
            ("credential_endpoint", "cloud_accounts", False),
            ("plain_endpoint", "policies", True),
        ]
    )
    def test_data_session_capture_follows_credential_redaction(self, _name: str, endpoint: str, captured: bool) -> None:
        result = _run(endpoint, [ScriptedResponse(json={"data": []})])

        assert result.raised is None
        data_session_options = [options for options in result.session_options if not options.get("redact_values")]
        assert [options.get("capture", True) for options in data_session_options] == [captured]


class TestGetRowsPagination:
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_next_page_on_foreign_host_is_not_followed(self) -> None:
        result = _run(
            "alerts",
            [
                ScriptedResponse(
                    json={"data": [{"alertId": 1}], "paging": {"urls": {"nextPage": "https://evil.com/api/v2/steal"}}},
                )
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["alertId"] for row in result.rows] == [1]
        assert len(result.requests[1:]) == 1

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_resume_continues_from_saved_window_and_page(self) -> None:
        resume_url = "https://mycompany.lacework.net/api/v2/Alerts/ResumeToken"
        result = _run(
            "alerts",
            [
                ScriptedResponse(json={"data": [{"alertId": 1}], "paging": {}}),
                ScriptedResponse(json={"data": [{"alertId": 2}], "paging": {}}),
            ],
            resume_state=LaceworkResumeConfig(
                window_start="2026-06-15T00:00:00.000Z",
                window_end="2026-06-15T06:00:00.000Z",
                next_page_url=resume_url,
            ),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 10, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["alertId"] for row in result.rows] == [1, 2]
        # First request resumes the in-flight page, then pagination continues into the next
        # window (06:00 -> now) instead of restarting from the stale watermark.
        assert (result.requests[1].method, result.requests[1].url) == ("GET", resume_url)
        assert result.requests[2].query == {
            "startTime": ("2026-06-15T06:00:00.000Z",),
            "endTime": ("2026-06-15T12:00:00.000Z",),
        }
        # The next window was checkpointed once the resumed window finished paging.
        assert result.saved_states == [
            LaceworkResumeConfig(
                window_start="2026-06-15T06:00:00.000Z",
                window_end="2026-06-15T12:00:00.000Z",
                next_page_url=None,
            )
        ]

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_resume_url_on_foreign_host_is_ignored(self) -> None:
        result = _run(
            "alerts",
            [ScriptedResponse(json={"data": [{"alertId": 1}], "paging": {}})],
            resume_state=LaceworkResumeConfig(
                window_start="2026-06-15T06:00:00.000Z",
                window_end="2026-06-15T12:00:00.000Z",
                next_page_url="https://evil.com/api/v2/steal",
            ),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 10, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["alertId"] for row in result.rows] == [1]
        assert result.requests[1].method == "GET"
        assert result.requests[1].origin == "https://mycompany.lacework.net"

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_204_no_data_yields_nothing(self) -> None:
        result = _run(
            "alerts",
            [ScriptedResponse(status=204)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.rows == []


class TestAuth:
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_token_exchanged_once_and_sent_as_bearer(self) -> None:
        next_url = "https://mycompany.lacework.net/api/v2/Alerts/AbCdEf123"
        result = _run(
            "alerts",
            [
                ScriptedResponse(json={"data": [{"alertId": 1}], "paging": {"urls": {"nextPage": next_url}}}),
                ScriptedResponse(json={"data": [{"alertId": 2}], "paging": {}}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.paths.count("/api/v2/access/tokens") == 1
        for request in result.requests[1:]:
            assert request.headers["authorization"] == "Bearer tok-123"

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_token_exchange_is_excluded_from_sample_capture(self) -> None:
        # The X-LW-UAKS request header and the response's generic `token` field are not caught by
        # the name-based sample scrubbers, so the auth session must opt out of capture and redact
        # the secret; without this an operator-enabled capture rule would persist credentials.
        result = _run(
            "alerts",
            [ScriptedResponse(json={"data": [], "paging": {}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
        )

        assert result.raised is None
        uncaptured = [options for options in result.session_options if options.get("capture") is False]
        assert len(uncaptured) == 1
        assert uncaptured[0].get("redact_values") == ("secret",)

        with scripted_network([ScriptedResponse(status=201, json={"token": "tok"})]) as network:
            validate_credentials("mycompany", "KEY_ID", "secret")
        assert network.session_options[0].get("capture") is False
        assert network.session_options[0].get("redact_values") == ("secret",)

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_retries_on_429_using_retry_after(self) -> None:
        result = _run(
            "alerts",
            [
                ScriptedResponse(status=429, json={"message": "rate limited"}, headers={"Retry-After": "0"}),
                ScriptedResponse(json={"data": [{"alertId": 1}], "paging": {}}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["alertId"] for row in result.rows] == [1]
        assert len(result.requests[1:]) == 2

    @parameterized.expand(
        [
            ("rate_limited_with_retry_after", 429, {"Retry-After": "7"}, 7.0),
            ("rate_limited_without_retry_after", 429, {}, None),
            ("rate_limited_with_unparseable_retry_after", 429, {"Retry-After": "soon"}, None),
            ("server_error_ignores_retry_after", 503, {"Retry-After": "7"}, None),
        ]
    )
    def test_a_status_that_keeps_failing_raises_the_retryable_error(
        self, _name: str, status: int, headers: dict[str, str], expected_retry_after: float | None
    ) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/access/tokens"):
                return _token()
            return ScriptedResponse(status=status, json={"message": "failing"}, headers=headers)

        driver = SourceDriver(
            LaceworkSource(), LaceworkSourceConfig(account_name="mycompany", key_id="KEY_ID", secret_key="secret")
        )
        with time_machine.travel("2026-06-15T12:00:00Z", tick=False):
            result = driver.run(
                "alerts",
                respond,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
            )

        assert isinstance(result.raised, LaceworkRetryableError)
        assert result.raised.retry_after == expected_retry_after
        assert f"status={status}" in str(result.raised)

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_result_set_row_cap_is_logged(self) -> None:
        logger = MagicMock()
        result = _run(
            "alerts",
            [ScriptedResponse(json={"data": [{"alertId": 1}], "paging": {"rows": 5000, "totalRows": 500_000}})],
            logger=logger,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert any("row cap" in str(call) for call in logger.warning.call_args_list)


class TestLaceworkSourceResponse:
    @parameterized.expand(
        [
            ("alerts", ["alertId"], ["startTime"]),
            ("vulnerabilities_hosts", None, ["startTime"]),
            ("compliance_evaluations_gcp", None, ["reportTime"]),
            ("audit_logs", None, ["createdTime"]),
            ("agent_info", None, None),
        ]
    )
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_source_response_shape(
        self, endpoint: str, expected_primary_keys: list[str] | None, expected_partition_keys: list[str] | None
    ) -> None:
        result = _run(
            endpoint,
            [ScriptedResponse(json={"data": [], "paging": {}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_primary_keys
        assert result.response.partition_keys == expected_partition_keys
        # Windowed results arrive in no documented order, so the watermark must only persist at
        # successful job end.
        assert result.response.sort_mode == "desc"
