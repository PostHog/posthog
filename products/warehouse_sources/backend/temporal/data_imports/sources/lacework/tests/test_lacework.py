from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.lacework.lacework import (
    INVALID_ACCOUNT_ERROR,
    LaceworkResumeConfig,
    _is_same_host,
    base_url,
    get_rows,
    lacework_source,
    normalize_account,
    validate_credentials,
)

_LACEWORK_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.lacework.lacework"


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.headers = headers or {}
        self.content = b"" if json_data is None else b"{}"
        self.text = "" if json_data is None else str(json_data)

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} Client Error: error for url: fake", response=requests.Response()
            )


class _FakeSession:
    def __init__(self, data_responses: list[_FakeResponse]) -> None:
        self.data_calls: list[tuple[str, str, dict[str, Any] | None, dict[str, str]]] = []
        self.token_calls = 0
        self._data_responses = list(data_responses)

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        if url.endswith("/access/tokens"):
            self.token_calls += 1
            return _FakeResponse(201, {"token": "tok-123", "expiresAt": "2100-01-01T00:00:00.000Z"})
        self.data_calls.append((method, url, kwargs.get("json"), kwargs.get("headers") or {}))
        return self._data_responses.pop(0)


class _FakeResumableManager:
    def __init__(self, state: LaceworkResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[LaceworkResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> LaceworkResumeConfig | None:
        return self._state

    def save_state(self, data: LaceworkResumeConfig) -> None:
        self.saved.append(data)


def _collect_rows(
    session: _FakeSession,
    endpoint: str,
    manager: _FakeResumableManager | None = None,
    **incremental: Any,
) -> list[dict]:
    rows: list[dict] = []
    with patch(f"{_LACEWORK_MODULE}.make_tracked_session", return_value=session):
        for batch in get_rows(
            account_name="mycompany",
            key_id="KEY_ID",
            secret_key="secret",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager or _FakeResumableManager(),  # type: ignore[arg-type]
            **incremental,
        ):
            rows.extend(batch)
    return rows


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
    def _validate(self, response: _FakeResponse) -> tuple[bool, str | None]:
        session = MagicMock()
        session.post.return_value = response
        with patch(f"{_LACEWORK_MODULE}.make_tracked_session", return_value=session):
            return validate_credentials("mycompany", "KEY_ID", "secret")

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_bad_credentials(self, _name: str, status_code: int) -> None:
        ok, message = self._validate(_FakeResponse(status_code, {"message": "unauthorized"}))
        assert ok is False
        assert message == "Invalid Lacework API key ID or secret key"

    def test_other_error_surfaces_api_message(self) -> None:
        ok, message = self._validate(_FakeResponse(400, {"message": "expiryTime out of range"}))
        assert ok is False
        assert message == "expiryTime out of range"

    def test_invalid_account_fails_without_network(self) -> None:
        with patch(f"{_LACEWORK_MODULE}.make_tracked_session") as mock_session:
            ok, message = validate_credentials("my company", "KEY_ID", "secret")
        assert ok is False
        assert message == INVALID_ACCOUNT_ERROR
        mock_session.assert_not_called()


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
        session = _FakeSession([_FakeResponse(200, {"data": [], "paging": {}})])
        _collect_rows(
            session,
            endpoint,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
        )

        _method, url, body, _headers = session.data_calls[0]
        assert url.endswith(f"/api/v2{path}")
        assert body is not None and body[param] == value

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_full_refresh_uses_default_lookback(self) -> None:
        # agent_info: 7-day lookback with 7-day windows -> exactly one request window.
        session = _FakeSession([_FakeResponse(200, {"data": [{"mid": 1}], "paging": {}})])
        rows = _collect_rows(session, "agent_info", should_use_incremental_field=False)

        assert rows == [{"mid": 1}]
        assert len(session.data_calls) == 1
        _method, _url, body, _headers = session.data_calls[0]
        assert body is not None and body["timeFilter"] == {
            "startTime": "2026-06-08T12:00:00.000Z",
            "endTime": "2026-06-15T12:00:00.000Z",
        }


class TestGetRowsUnwindowed:
    def test_list_endpoint_pages_without_time_range_and_strips_credentials(self) -> None:
        next_url = "https://mycompany.lacework.net/api/v2/CloudAccounts/page2"
        session = _FakeSession(
            [
                _FakeResponse(
                    200,
                    {
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
                _FakeResponse(
                    200,
                    {"data": [{"intgGuid": "B", "data": {"credentials": {"clientSecret": "s"}, "tenantId": "t"}}]},
                ),
            ]
        )
        manager = _FakeResumableManager()
        rows = _collect_rows(session, "cloud_accounts", manager=manager)

        assert rows == [
            {"intgGuid": "A", "data": {"awsAccountId": "123"}},
            {"intgGuid": "B", "data": {"tenantId": "t"}},
        ]
        assert [(m, u, b) for m, u, b, _h in session.data_calls] == [
            ("GET", "https://mycompany.lacework.net/api/v2/CloudAccounts", None),
            ("GET", next_url, None),
        ]
        assert manager.saved == []

    @parameterized.expand(
        [
            ("credential_endpoint", "cloud_accounts", False),
            ("plain_endpoint", "policies", True),
        ]
    )
    def test_data_session_capture_follows_credential_redaction(self, _name: str, endpoint: str, captured: bool) -> None:
        session = _FakeSession([_FakeResponse(200, {"data": []})])
        with patch(f"{_LACEWORK_MODULE}.make_tracked_session", return_value=session) as mock_make:
            list(
                get_rows(
                    account_name="mycompany",
                    key_id="KEY_ID",
                    secret_key="secret",
                    endpoint=endpoint,
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )

        data_session_calls = [c for c in mock_make.call_args_list if not c.kwargs.get("redact_values")]
        assert [c.kwargs.get("capture", True) for c in data_session_calls] == [captured]


class TestGetRowsPagination:
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_next_page_on_foreign_host_is_not_followed(self) -> None:
        session = _FakeSession(
            [
                _FakeResponse(
                    200,
                    {"data": [{"alertId": 1}], "paging": {"urls": {"nextPage": "https://evil.com/api/v2/steal"}}},
                )
            ]
        )
        rows = _collect_rows(
            session,
            "alerts",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
        )

        assert [r["alertId"] for r in rows] == [1]
        assert len(session.data_calls) == 1

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_resume_continues_from_saved_window_and_page(self) -> None:
        resume_url = "https://mycompany.lacework.net/api/v2/Alerts/ResumeToken"
        manager = _FakeResumableManager(
            LaceworkResumeConfig(
                window_start="2026-06-15T00:00:00.000Z",
                window_end="2026-06-15T06:00:00.000Z",
                next_page_url=resume_url,
            )
        )
        session = _FakeSession(
            [
                _FakeResponse(200, {"data": [{"alertId": 1}], "paging": {}}),
                _FakeResponse(200, {"data": [{"alertId": 2}], "paging": {}}),
            ]
        )
        rows = _collect_rows(
            session,
            "alerts",
            manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 10, tzinfo=UTC),
        )

        assert [r["alertId"] for r in rows] == [1, 2]
        # First request resumes the in-flight page, then pagination continues into the next
        # window (06:00 -> now) instead of restarting from the stale watermark.
        assert session.data_calls[0][:2] == ("GET", resume_url)
        parsed = urlparse(session.data_calls[1][1])
        assert parse_qs(parsed.query) == {
            "startTime": ["2026-06-15T06:00:00.000Z"],
            "endTime": ["2026-06-15T12:00:00.000Z"],
        }
        # The next window was checkpointed once the resumed window finished paging.
        assert manager.saved == [
            LaceworkResumeConfig(
                window_start="2026-06-15T06:00:00.000Z",
                window_end="2026-06-15T12:00:00.000Z",
                next_page_url=None,
            )
        ]

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_resume_url_on_foreign_host_is_ignored(self) -> None:
        manager = _FakeResumableManager(
            LaceworkResumeConfig(
                window_start="2026-06-15T06:00:00.000Z",
                window_end="2026-06-15T12:00:00.000Z",
                next_page_url="https://evil.com/api/v2/steal",
            )
        )
        session = _FakeSession([_FakeResponse(200, {"data": [{"alertId": 1}], "paging": {}})])
        rows = _collect_rows(
            session,
            "alerts",
            manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 10, tzinfo=UTC),
        )

        assert [r["alertId"] for r in rows] == [1]
        method, url, _body, _headers = session.data_calls[0]
        assert method == "GET"
        assert urlparse(url).hostname == "mycompany.lacework.net"

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_204_no_data_yields_nothing(self) -> None:
        session = _FakeSession([_FakeResponse(204, None)])
        rows = _collect_rows(
            session,
            "alerts",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
        )

        assert rows == []


class TestAuth:
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_token_exchanged_once_and_sent_as_bearer(self) -> None:
        next_url = "https://mycompany.lacework.net/api/v2/Alerts/AbCdEf123"
        session = _FakeSession(
            [
                _FakeResponse(200, {"data": [{"alertId": 1}], "paging": {"urls": {"nextPage": next_url}}}),
                _FakeResponse(200, {"data": [{"alertId": 2}], "paging": {}}),
            ]
        )
        _collect_rows(
            session,
            "alerts",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
        )

        assert session.token_calls == 1
        for _method, _url, _body, headers in session.data_calls:
            assert headers["Authorization"] == "Bearer tok-123"

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_token_exchange_is_excluded_from_sample_capture(self) -> None:
        # The X-LW-UAKS request header and the response's generic `token` field are not caught by
        # the name-based sample scrubbers, so the auth session must opt out of capture and redact
        # the secret; without this an operator-enabled capture rule would persist credentials.
        session = _FakeSession([_FakeResponse(200, {"data": [], "paging": {}})])
        with patch(f"{_LACEWORK_MODULE}.make_tracked_session", return_value=session) as mock_make:
            list(
                get_rows(
                    account_name="mycompany",
                    key_id="KEY_ID",
                    secret_key="secret",
                    endpoint="alerts",
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
                )
            )

        uncaptured = [c for c in mock_make.call_args_list if c.kwargs.get("capture") is False]
        assert len(uncaptured) == 1
        assert uncaptured[0].kwargs.get("redact_values") == ("secret",)

        mock_validate_session = MagicMock()
        mock_validate_session.post.return_value = _FakeResponse(201, {"token": "tok"})
        with patch(f"{_LACEWORK_MODULE}.make_tracked_session", return_value=mock_validate_session) as mock_make:
            validate_credentials("mycompany", "KEY_ID", "secret")
        assert mock_make.call_args.kwargs.get("capture") is False
        assert mock_make.call_args.kwargs.get("redact_values") == ("secret",)

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_retries_on_429_using_retry_after(self) -> None:
        session = _FakeSession(
            [
                _FakeResponse(429, {"message": "rate limited"}, headers={"Retry-After": "0"}),
                _FakeResponse(200, {"data": [{"alertId": 1}], "paging": {}}),
            ]
        )
        rows = _collect_rows(
            session,
            "alerts",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
        )

        assert [r["alertId"] for r in rows] == [1]
        assert len(session.data_calls) == 2

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_result_set_row_cap_is_logged(self) -> None:
        session = _FakeSession(
            [_FakeResponse(200, {"data": [{"alertId": 1}], "paging": {"rows": 5000, "totalRows": 500_000}})]
        )
        logger = MagicMock()
        with patch(f"{_LACEWORK_MODULE}.make_tracked_session", return_value=session):
            list(
                get_rows(
                    account_name="mycompany",
                    key_id="KEY_ID",
                    secret_key="secret",
                    endpoint="alerts",
                    logger=logger,
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 6, 15, 6, 0, tzinfo=UTC),
                )
            )

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
    def test_source_response_shape(
        self, endpoint: str, expected_primary_keys: list[str] | None, expected_partition_keys: list[str] | None
    ) -> None:
        response = lacework_source(
            account_name="mycompany",
            key_id="KEY_ID",
            secret_key="secret",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )

        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        assert response.partition_keys == expected_partition_keys
        # Windowed results arrive in no documented order, so the watermark must only persist at
        # successful job end.
        assert response.sort_mode == "desc"
