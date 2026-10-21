import ssl
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.metabase import (
    MetabaseAuthMethodConfig,
    MetabaseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metabase import metabase as metabase_module
from products.warehouse_sources.backend.temporal.data_imports.sources.metabase.metabase import (
    API_KEY_AUTH,
    SESSION_AUTH,
    SESSION_RESPONSE_NOT_JSON_ERROR,
    MetabaseAuth,
    MetabaseAuthError,
    MetabaseHostNotAllowedError,
    MetabaseQueryLogsUnavailableError,
    MetabaseResumeConfig,
    _resolve_auth_headers,
    normalize_host,
    query_execution_months,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metabase.source import MetabaseSource


def _api_key_auth() -> MetabaseAuth:
    return MetabaseAuth(method=API_KEY_AUTH, api_key="mb_secret")


def _session_auth() -> MetabaseAuth:
    return MetabaseAuth(method=SESSION_AUTH, username="me@example.com", password="hunter2")


def _driver(*, session_auth: bool = False) -> SourceDriver:
    auth = (
        MetabaseAuthMethodConfig(selection="session", username="me@example.com", password="hunter2")
        if session_auth
        else MetabaseAuthMethodConfig(selection="api_key", api_key="mb_secret")
    )
    return SourceDriver(MetabaseSource(), MetabaseSourceConfig(host="https://x.metabaseapp.com", auth_method=auth))


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://company.metabaseapp.com", "https://company.metabaseapp.com"),
            ("company.metabaseapp.com", "https://company.metabaseapp.com"),
            ("https://company.metabaseapp.com/", "https://company.metabaseapp.com"),
            ("https://company.metabaseapp.com/api", "https://company.metabaseapp.com"),
            ("  company.metabaseapp.com  ", "https://company.metabaseapp.com"),
            ("http://localhost:3000", "http://localhost:3000"),
            ("http://127.0.0.1:3000", "http://127.0.0.1:3000"),
            # Plaintext HTTP to a remote host is upgraded to HTTPS so credentials aren't sent in the clear.
            ("http://company.metabaseapp.com", "https://company.metabaseapp.com"),
            ("HTTP://company.metabaseapp.com/api", "https://company.metabaseapp.com"),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected


class TestQueryExecutionMonths:
    @pytest.mark.parametrize(
        "now, last_value, first, last, count",
        [
            # Full refresh walks back the default retention window.
            (datetime(2026, 3, 10, tzinfo=UTC), None, "2024-03", "2026-03", 25),
            # Incremental starts one month before the watermark, across a year boundary.
            (datetime(2026, 2, 10, tzinfo=UTC), "2026-01-05T08:00:00Z", "2025-12", "2026-02", 3),
            (datetime(2026, 2, 10, tzinfo=UTC), datetime(2026, 2, 1, 0, 30), "2026-01", "2026-02", 2),
        ],
    )
    def test_month_windows(self, now, last_value, first, last, count):
        months = query_execution_months(now, last_value)
        assert (months[0], months[-1], len(months)) == (first, last, count)
        assert months == sorted(set(months))


class TestResolveAuthHeaders:
    def test_api_key_missing_raises(self):
        auth = MetabaseAuth(method=API_KEY_AUTH, api_key=None)
        with pytest.raises(MetabaseAuthError):
            _resolve_auth_headers("https://x.metabaseapp.com", auth, mock.MagicMock())

    @pytest.mark.parametrize("status_code", [400, 401, 403])
    def test_session_bad_credentials_raises_auth_error(self, status_code):
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            with pytest.raises(MetabaseAuthError):
                _resolve_auth_headers("https://x.metabaseapp.com", _session_auth(), mock.MagicMock())
        assert network.requests_log[0].path == "/api/session"
        assert network.requests_log[0].json() == {"username": "me@example.com", "password": "hunter2"}

    def test_session_missing_username_raises(self):
        auth = MetabaseAuth(method=SESSION_AUTH, username=None, password="x")
        with pytest.raises(MetabaseAuthError):
            _resolve_auth_headers("https://x.metabaseapp.com", auth, mock.MagicMock())

    def test_session_no_token_in_response_raises(self):
        with scripted_network([ScriptedResponse(json={})]):
            with pytest.raises(MetabaseAuthError):
                _resolve_auth_headers("https://x.metabaseapp.com", _session_auth(), mock.MagicMock())

    def test_session_non_json_body_raises_auth_error(self):
        # A 2xx whose body isn't JSON (host isn't a Metabase API) must surface as a non-retryable
        # MetabaseAuthError, not a raw JSONDecodeError bubbling out of the activity.
        with scripted_network([ScriptedResponse(body=b"not json")]):
            with pytest.raises(MetabaseAuthError) as exc:
                _resolve_auth_headers("https://x.metabaseapp.com", _session_auth(), mock.MagicMock())
        assert SESSION_RESPONSE_NOT_JSON_ERROR in str(exc.value)

    @pytest.mark.parametrize("status_code", [404, 422, 500])
    def test_session_unexpected_status_raises_retryable_not_httperror(self, status_code):
        # Unexpected non-auth statuses must surface as a typed retryable error so callers'
        # except clauses catch them, not a raw requests HTTPError.
        with scripted_network([ScriptedResponse(status=status_code)]):
            with pytest.raises(metabase_module.MetabaseRetryableError):
                _resolve_auth_headers("https://x.metabaseapp.com", _session_auth(), mock.MagicMock())


class TestValidateCredentials:
    def test_success(self):
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("https://x.metabaseapp.com", _api_key_auth()) == (True, None)
        assert network.requests_log[0].path == "/api/user/current"
        assert network.requests_log[0].headers["x-api-key"] == "mb_secret"

    def test_403_at_source_create_is_accepted(self):
        with scripted_network([ScriptedResponse(status=403)]):
            assert validate_credentials("https://x.metabaseapp.com", _api_key_auth(), schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with scripted_network([ScriptedResponse(status=403)]):
            valid, msg = validate_credentials("https://x.metabaseapp.com", _api_key_auth(), schema_name="cards")
            assert valid is False
            assert msg is not None

    @pytest.mark.parametrize("bad_host", ["", "https://", "not a host!"])
    def test_invalid_host_short_circuits(self, bad_host):
        valid, msg = validate_credentials(bad_host, _api_key_auth())
        assert valid is False
        assert msg == "Invalid Metabase host"

    def test_connection_error_does_not_leak_raw_exception(self):
        # requests connection errors embed the customer's host/IP and give the user nothing to act
        # on. The (fictional-range) IP and the raw blob must never reach the user; a friendly,
        # actionable message must.
        raw = "HTTPSConnectionPool(host='203.0.113.10', port=3000): Max retries exceeded"
        with scripted_network(always(ConnectionResetError(raw))):
            valid, msg = validate_credentials("https://x.metabaseapp.com", _api_key_auth())
            assert valid is False
            assert msg is not None
            assert "203.0.113.10" not in msg
            assert "HTTPSConnectionPool" not in msg
            assert "Instance URL" in msg

    def test_wrong_version_number_points_at_https(self):
        # HTTPS forced onto a plaintext port surfaces as SSL WRONG_VERSION_NUMBER; the guidance
        # should tell the user the instance must be served over HTTPS, without leaking the host.
        raw = "HTTPSConnectionPool(host='203.0.113.10', port=3000): SSLError([SSL: WRONG_VERSION_NUMBER])"
        with scripted_network(always(ssl.SSLError(raw))):
            valid, msg = validate_credentials("https://x.metabaseapp.com", _api_key_auth())
            assert valid is False
            assert msg is not None
            assert "203.0.113.10" not in msg
            assert "HTTPS" in msg

    def test_rejects_redirect_response(self):
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://internal.example/redirected"})]
        ) as network:
            valid, msg = validate_credentials("https://x.metabaseapp.com", _api_key_auth())
        assert valid is False
        assert msg == metabase_module.REDIRECT_NOT_FOLLOWED_ERROR
        assert [request.path for request in network.requests_log] == ["/api/user/current"]

    def test_blocks_unsafe_host(self):
        with scripted_network([]) as network:
            with mock.patch.object(metabase_module, "_is_host_safe", return_value=(False, "internal address")):
                valid, msg = validate_credentials("https://10.0.0.1", _api_key_auth(), team_id=99)
        assert valid is False
        assert msg == "internal address"
        assert network.requests_log == []

    def test_unexpected_session_status_returns_failure_not_raises(self):
        # A 404 (e.g. wrong API path) during session minting must come back as (False, msg), not an
        # uncaught HTTPError bubbling out of source creation.
        with scripted_network([ScriptedResponse(status=404)]) as network:
            valid, msg = validate_credentials("https://x.metabaseapp.com", _session_auth())
        assert valid is False
        assert msg is not None
        assert [request.path for request in network.requests_log] == ["/api/session"]

    def test_unexpected_status_does_not_leak_response_body(self):
        # When the host isn't a Metabase instance it returns an arbitrary body (e.g. a hosting
        # provider's error page). That body must never reach the user — only a friendly,
        # status-coded message that points them back at the Instance URL.
        leaked_body = '{"error": {"code": "404", "message": "SENTINEL_UPSTREAM_BODY"}}'
        with scripted_network([ScriptedResponse(status=404, body=leaked_body.encode())]):
            valid, msg = validate_credentials("https://x.metabaseapp.com", _api_key_auth())
            assert valid is False
            assert msg is not None
            assert "SENTINEL_UPSTREAM_BODY" not in msg
            assert "404" in msg


class TestMetabaseSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, partition_key",
        [
            ("cards", ["id"], "created_at"),
            ("dashboards", ["id"], "created_at"),
            ("databases", ["id"], "created_at"),
            ("native_query_snippets", ["id"], "created_at"),
            ("users", ["id"], "date_joined"),
            ("collections", ["id"], None),
        ],
    )
    def test_response_shape(self, endpoint, primary_keys, partition_key):
        result = _driver().run(endpoint, always(ScriptedResponse(json=[])))
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestGetRows:
    """Drives the new rest_source transport: a single unpaginated GET per endpoint, with the auth
    header, host guard, and redirect refusal preserved from the hand-rolled implementation."""

    def test_yields_wrapped_array(self):
        result = _driver().run("databases", [ScriptedResponse(json={"data": [{"id": 7}], "total": 1})])
        assert result.raised is None
        assert [row["id"] for row in result.rows] == [7]
        assert result.paths == ["/api/database"]

    def test_does_not_follow_a_redirect_to_another_path_on_the_host(self):
        redirect = ScriptedResponse(status=302, headers={"Location": "https://x.metabaseapp.com/api/elsewhere"})
        result = _driver().run("cards", [redirect, ScriptedResponse(json=[{"id": 1}])])
        assert result.paths == ["/api/card"]
        assert result.rows == []

    def test_rejects_redirect(self):
        # allow_redirects=False makes the client refuse any 3xx rather than following it off-host.
        result = _driver().run(
            "cards", [ScriptedResponse(status=302, headers={"Location": "https://internal.example/redirected"})]
        )
        assert result.paths == ["/api/card"]
        assert isinstance(result.raised, ValueError)
        assert "redirect" in str(result.raised).lower()

    def test_blocks_unsafe_host_at_runtime(self):
        with mock.patch.object(metabase_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _driver().run("cards", [])
        assert isinstance(result.raised, MetabaseHostNotAllowedError)
        assert result.requests == []

    def test_session_auth_mints_token_then_lists(self):
        result = _driver(session_auth=True).run(
            "cards",
            route(
                {
                    "/api/session": [ScriptedResponse(json={"id": "tok-123"})],
                    "/api/card": [ScriptedResponse(json=[{"id": 1}])],
                }
            ),
        )
        assert result.raised is None
        assert result.paths == ["/api/session", "/api/card"]
        assert result.requests[0].method == "POST"
        assert result.requests[0].json() == {"username": "me@example.com", "password": "hunter2"}
        # The minted token — not the username/password — is what the data request carries.
        headers = result.requests[1].headers
        assert headers["x-metabase-session"] == "tok-123"
        assert "x-api-key" not in headers
        assert [row["id"] for row in result.rows] == [1]

    def test_memberships_flatten_user_map(self):
        body = {
            "1": [{"membership_id": 10, "group_id": 1, "user_id": 1, "is_group_manager": False}],
            "2": [
                {"membership_id": 11, "group_id": 1, "user_id": 2, "is_group_manager": False},
                {"membership_id": 12, "group_id": 3, "user_id": 2, "is_group_manager": True},
            ],
        }
        result = _driver().run("permission_group_memberships", [ScriptedResponse(json=body)])
        assert result.raised is None
        assert result.paths == ["/api/permissions/membership"]
        assert [(r["membership_id"], r["user_id"]) for r in result.rows] == [(10, 1), (11, 2), (12, 2)]

    def test_fields_fan_out_over_databases(self):
        result = _driver().run(
            "fields",
            [
                ScriptedResponse(json={"data": [{"id": 1}, {"id": 2}], "total": 2}),
                ScriptedResponse(json=[{"id": 100, "table_id": 5, "name": "email"}]),
                ScriptedResponse(json=[{"id": 200, "table_id": 9, "name": "amount"}]),
            ],
        )
        assert result.raised is None
        assert result.paths == ["/api/database", "/api/database/1/fields", "/api/database/2/fields"]
        assert [(r["id"], r["database_id"]) for r in result.rows] == [(100, 1), (200, 2)]

    @pytest.mark.parametrize(
        "last_value, resume_month, expected_ids, expected_requests",
        [
            (None, None, [1, 2, 3, 4], 25),
            # Rows before the watermark drop out; the month before the watermark is still fetched.
            ("2026-03-20T00:00:00Z", None, [3, 4], 3),
            (None, "2026-02", [1, 2, 3, 4], 3),
        ],
    )
    def test_query_executions_walk_months_ascending(
        self, last_value: str | None, resume_month: str | None, expected_ids: list[int], expected_requests: int
    ):
        february = [{"id": 1, "started_at": "2026-02-15T10:00:00+00:00"}]
        # Metabase returns each month newest first.
        march = [{"id": 3, "started_at": "2026-03-25T10:00:00Z"}, {"id": 2, "started_at": "2026-03-02T10:00:00Z"}]
        april = [{"id": 4, "started_at": "2026-04-02T10:00:00Z"}]
        responses = [ScriptedResponse(json=[]) for _ in range(expected_requests - 3)] + [
            ScriptedResponse(json=month) for month in (february, march, april)
        ]
        inputs: dict[str, Any] = {}
        if last_value is not None:
            inputs = {"incremental_field": "started_at", "db_incremental_field_last_value": last_value}

        with time_machine.travel(datetime(2026, 4, 10, tzinfo=UTC), tick=False):
            result = _driver().run(
                "query_executions",
                responses,
                resume_state=MetabaseResumeConfig(next_month=resume_month) if resume_month else None,
                **inputs,
            )

        assert result.raised is None
        assert [r["id"] for r in result.rows] == expected_ids
        assert len(result.requests) == expected_requests
        assert result.paths[-1] == "/api/ee/logs/query_execution/2026-04"
        assert [state.next_month for state in result.saved_states][-2:] == ["2026-03", "2026-04"]

    @pytest.mark.parametrize("status_code", [402, 404])
    def test_query_executions_unavailable_is_typed(self, status_code):
        result = _driver().run("query_executions", always(ScriptedResponse(status=status_code)))
        assert isinstance(result.raised, MetabaseQueryLogsUnavailableError)
