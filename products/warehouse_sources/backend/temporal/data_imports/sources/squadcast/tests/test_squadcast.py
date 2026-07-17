import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.squadcast.settings import SQUADCAST_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.squadcast.squadcast import (
    FULL_REFRESH_START,
    PAGE_SIZE,
    SquadcastAuthError,
    SquadcastResumeConfig,
    get_rows,
    squadcast_source,
    validate_credentials,
)

SQUADCAST_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.squadcast.squadcast"

US_AUTH_URL = "https://auth.squadcast.com/oauth/access-token"
US_API = "https://api.squadcast.com"


class FakeResumableManager:
    """In-memory stand-in for ResumableSourceManager that records saved state."""

    def __init__(self, resume_state: Optional[SquadcastResumeConfig] = None) -> None:
        self._resume_state = resume_state
        self.saved_states: list[SquadcastResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume_state is not None

    def load_state(self) -> Optional[SquadcastResumeConfig]:
        return self._resume_state

    def save_state(self, data: SquadcastResumeConfig) -> None:
        self.saved_states.append(data)


def _mock_response(status_code: int = 200, body: Any = None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.text = text
    response.json.return_value = body if body is not None else {}
    if not response.ok:
        error_response = requests.Response()
        error_response.status_code = status_code
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Client Error: error for url: https://api.squadcast.com", response=error_response
        )
    return response


def _auth_body(expires_in_seconds: float = 3600) -> dict[str, Any]:
    return {"data": {"access_token": "jwt_abc", "expires_at": time.time() + expires_in_seconds}}


class FakeSession:
    """Dispatches session.get by URL so tests don't depend on exact request ordering."""

    def __init__(self, handler: Callable[[str, dict[str, str]], MagicMock]) -> None:
        self.handler = handler
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, headers: Optional[dict[str, str]] = None, timeout: Any = None) -> MagicMock:
        self.calls.append((url, headers or {}))
        return self.handler(url, headers or {})

    def calls_to(self, path: str) -> list[tuple[str, dict[str, str]]]:
        return [call for call in self.calls if urlparse(call[0]).path == path]


def _params(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


def _standard_handler(
    teams: list[dict[str, Any]],
    endpoint_responses: dict[str, Callable[[str], MagicMock]],
    auth_expires_in: float = 3600,
) -> Callable[[str, dict[str, str]], MagicMock]:
    def handler(url: str, headers: dict[str, str]) -> MagicMock:
        path = urlparse(url).path
        if path == "/oauth/access-token":
            return _mock_response(200, body=_auth_body(auth_expires_in))
        if path == "/v3/teams" and "/v3/teams" not in endpoint_responses:
            return _mock_response(200, body={"data": teams})
        if path in endpoint_responses:
            return endpoint_responses[path](url)
        raise AssertionError(f"unexpected request: {url}")

    return handler


def _run_get_rows(
    session: FakeSession,
    endpoint: str,
    manager: Optional[FakeResumableManager] = None,
    **kwargs: Any,
) -> list[list[dict[str, Any]]]:
    with patch(f"{SQUADCAST_MODULE}.make_tracked_session", return_value=session):
        return list(
            get_rows(
                "refresh_tok",
                "us",
                endpoint,
                MagicMock(),
                manager if manager is not None else FakeResumableManager(),  # type: ignore[arg-type]
                **kwargs,
            )
        )


class TestAuth:
    def test_bearer_token_from_refresh_exchange_is_sent_to_api(self) -> None:
        session = FakeSession(
            _standard_handler(
                teams=[],
                endpoint_responses={"/v3/users": lambda url: _mock_response(200, body={"data": [{"id": "u1"}]})},
            )
        )
        batches = _run_get_rows(session, "users")

        assert batches == [[{"id": "u1"}]]
        auth_calls = session.calls_to("/oauth/access-token")
        assert auth_calls[0][1]["X-Refresh-Token"] == "refresh_tok"
        user_calls = session.calls_to("/v3/users")
        assert user_calls[0][1]["Authorization"] == "Bearer jwt_abc"

    def test_access_token_reused_while_valid(self) -> None:
        session = FakeSession(
            _standard_handler(
                teams=[{"id": "t1"}, {"id": "t2"}],
                endpoint_responses={"/v3/services": lambda url: _mock_response(200, body={"data": [{"id": "s"}]})},
            )
        )
        _run_get_rows(session, "services")

        assert len(session.calls_to("/oauth/access-token")) == 1

    def test_expired_access_token_is_re_exchanged(self) -> None:
        # expires_at in the past forces a re-exchange before every API request.
        session = FakeSession(
            _standard_handler(
                teams=[{"id": "t1"}],
                endpoint_responses={"/v3/services": lambda url: _mock_response(200, body={"data": [{"id": "s"}]})},
                auth_expires_in=-100,
            )
        )
        _run_get_rows(session, "services")

        # One exchange per API request (teams + services).
        assert len(session.calls_to("/oauth/access-token")) == 2

    def test_rejected_refresh_token_raises_auth_error(self) -> None:
        def handler(url: str, headers: dict[str, str]) -> MagicMock:
            return _mock_response(401, body={"meta": {"status": 401, "error_message": "invalid token"}})

        session = FakeSession(handler)
        with pytest.raises(SquadcastAuthError, match="Squadcast refresh token was rejected"):
            _run_get_rows(session, "users")

    def test_eu_region_uses_eu_hosts(self) -> None:
        urls: list[str] = []

        def handler(url: str, headers: dict[str, str]) -> MagicMock:
            urls.append(url)
            if "/oauth/access-token" in url:
                return _mock_response(200, body=_auth_body())
            return _mock_response(200, body={"data": []})

        session = FakeSession(handler)
        with patch(f"{SQUADCAST_MODULE}.make_tracked_session", return_value=session):
            list(get_rows("refresh_tok", "eu", "users", MagicMock(), FakeResumableManager()))  # type: ignore[arg-type]

        assert urls[0].startswith("https://auth.eu.squadcast.com/")
        assert urls[1].startswith("https://api.eu.squadcast.com/")


class TestCredentialHardening:
    # The refresh token is long-lived: dropping redaction would persist it via HTTP sample
    # capture, and following redirects would replay credentialed headers to the target.
    def _assert_hardened(self, factory: MagicMock) -> None:
        assert factory.call_args_list
        for call in factory.call_args_list:
            assert call.kwargs["redact_values"] == ("refresh_tok",)
            assert call.kwargs["allow_redirects"] is False
        # The token exchange session is excluded from sample capture — its response body
        # carries the minted tokens.
        assert any(call.kwargs.get("capture") is False for call in factory.call_args_list)

    def test_sync_sessions_are_hardened(self) -> None:
        session = FakeSession(
            _standard_handler(
                teams=[],
                endpoint_responses={"/v3/users": lambda url: _mock_response(200, body={"data": [{"id": "u1"}]})},
            )
        )
        with patch(f"{SQUADCAST_MODULE}.make_tracked_session", return_value=session) as factory:
            list(get_rows("refresh_tok", "us", "users", MagicMock(), FakeResumableManager()))  # type: ignore[arg-type]

        self._assert_hardened(factory)

    def test_validate_credentials_sessions_are_hardened(self) -> None:
        session = FakeSession(
            lambda url, headers: (
                _mock_response(200, body=_auth_body())
                if "/oauth/access-token" in url
                else _mock_response(200, body={"data": []})
            )
        )
        with patch(f"{SQUADCAST_MODULE}.make_tracked_session", return_value=session) as factory:
            validate_credentials("refresh_tok", "us")

        self._assert_hardened(factory)


class TestTeamFanOut:
    def test_rows_fetched_per_team_and_stamped_with_team_id(self) -> None:
        def services(url: str) -> MagicMock:
            team = _params(url)["owner_id"]
            return _mock_response(200, body={"data": [{"id": f"svc_{team}"}]})

        session = FakeSession(
            _standard_handler(teams=[{"id": "t1"}, {"id": "t2"}], endpoint_responses={"/v3/services": services})
        )
        batches = _run_get_rows(session, "services")

        assert batches == [
            [{"id": "svc_t1", "team_id": "t1"}],
            [{"id": "svc_t2", "team_id": "t2"}],
        ]

    def test_services_api_key_never_reaches_yielded_rows(self) -> None:
        # The services payload carries the live key alert sources use to send events;
        # syncing it would expose it to anyone who can read the warehouse table.
        def services(url: str) -> MagicMock:
            return _mock_response(200, body={"data": [{"id": "svc_1", "api_key": "sq_live_key", "name": "checkout"}]})

        session = FakeSession(_standard_handler(teams=[{"id": "t1"}], endpoint_responses={"/v3/services": services}))
        batches = _run_get_rows(session, "services")

        assert batches == [[{"id": "svc_1", "name": "checkout", "team_id": "t1"}]]

    def test_team_without_access_is_skipped(self) -> None:
        def services(url: str) -> MagicMock:
            team = _params(url)["owner_id"]
            if team == "t2":
                return _mock_response(403, text="forbidden")
            return _mock_response(200, body={"data": [{"id": f"svc_{team}"}]})

        session = FakeSession(
            _standard_handler(
                teams=[{"id": "t1"}, {"id": "t2"}, {"id": "t3"}], endpoint_responses={"/v3/services": services}
            )
        )
        batches = _run_get_rows(session, "services")

        assert [batch[0]["id"] for batch in batches] == ["svc_t1", "svc_t3"]

    def test_non_permission_error_fails_the_sync(self) -> None:
        session = FakeSession(
            _standard_handler(
                teams=[{"id": "t1"}],
                endpoint_responses={"/v3/services": lambda url: _mock_response(400, text="bad request")},
            )
        )
        with pytest.raises(requests.HTTPError):
            _run_get_rows(session, "services")

    def test_team_bookmark_saved_between_teams(self) -> None:
        manager = FakeResumableManager()
        session = FakeSession(
            _standard_handler(
                teams=[{"id": "t1"}, {"id": "t2"}],
                endpoint_responses={"/v3/services": lambda url: _mock_response(200, body={"data": [{"id": "s"}]})},
            )
        )
        _run_get_rows(session, "services", manager)

        assert [(s.team_id, s.cursor) for s in manager.saved_states] == [("t2", None)]

    def test_resume_skips_completed_teams(self) -> None:
        manager = FakeResumableManager(resume_state=SquadcastResumeConfig(team_id="t2", cursor=None))

        def services(url: str) -> MagicMock:
            return _mock_response(200, body={"data": [{"id": f"svc_{_params(url)['owner_id']}"}]})

        session = FakeSession(
            _standard_handler(
                teams=[{"id": "t1"}, {"id": "t2"}, {"id": "t3"}], endpoint_responses={"/v3/services": services}
            )
        )
        batches = _run_get_rows(session, "services", manager)

        assert [batch[0]["id"] for batch in batches] == ["svc_t2", "svc_t3"]

    def test_resume_with_missing_team_starts_over(self) -> None:
        manager = FakeResumableManager(resume_state=SquadcastResumeConfig(team_id="gone", cursor=None))

        def services(url: str) -> MagicMock:
            return _mock_response(200, body={"data": [{"id": f"svc_{_params(url)['owner_id']}"}]})

        session = FakeSession(_standard_handler(teams=[{"id": "t1"}], endpoint_responses={"/v3/services": services}))
        batches = _run_get_rows(session, "services", manager)

        assert [batch[0]["id"] for batch in batches] == ["svc_t1"]


class TestOffsetPagination:
    def test_paginates_slos_and_saves_state_after_yield(self) -> None:
        manager = FakeResumableManager()
        full_page = [{"id": i} for i in range(PAGE_SIZE)]

        def slos(url: str) -> MagicMock:
            offset = int(_params(url)["offset"])
            body = {"data": {"slos": full_page if offset == 0 else [{"id": "last"}]}}
            return _mock_response(200, body=body)

        session = FakeSession(_standard_handler(teams=[{"id": "t1"}], endpoint_responses={"/v3/slo": slos}))
        batches = _run_get_rows(session, "slos", manager)

        assert len(batches) == 2
        assert len(batches[0]) == PAGE_SIZE
        assert batches[1][0]["id"] == "last"
        assert [(s.team_id, s.cursor) for s in manager.saved_states] == [("t1", str(PAGE_SIZE))]

    def test_resumes_from_saved_offset(self) -> None:
        manager = FakeResumableManager(resume_state=SquadcastResumeConfig(team_id="t1", cursor=str(PAGE_SIZE)))

        def slos(url: str) -> MagicMock:
            assert _params(url)["offset"] == str(PAGE_SIZE)
            return _mock_response(200, body={"data": {"slos": [{"id": "x"}]}})

        session = FakeSession(_standard_handler(teams=[{"id": "t1"}], endpoint_responses={"/v3/slo": slos}))
        batches = _run_get_rows(session, "slos", manager)

        assert batches == [[{"id": "x", "team_id": "t1"}]]


class TestCursorPagination:
    def test_follows_next_cursor_until_has_next_is_false(self) -> None:
        manager = FakeResumableManager()

        def schedules(url: str) -> MagicMock:
            params = _params(url)
            assert params["teamID"] == "t1"
            if "cursor" not in params:
                return _mock_response(
                    200,
                    body={"data": [{"id": 1}], "pageInfo": {"hasNext": True, "nextCursor": "cur_2", "hasPrev": False}},
                )
            assert params["cursor"] == "cur_2"
            return _mock_response(200, body={"data": [{"id": 2}], "pageInfo": {"hasNext": False, "hasPrev": True}})

        session = FakeSession(_standard_handler(teams=[{"id": "t1"}], endpoint_responses={"/v4/schedules": schedules}))
        batches = _run_get_rows(session, "schedules", manager)

        assert [batch[0]["id"] for batch in batches] == [1, 2]
        assert [(s.team_id, s.cursor) for s in manager.saved_states] == [("t1", "cur_2")]


class TestIncidentExport:
    def test_incremental_windows_start_at_last_value(self) -> None:
        last_value = datetime.now(UTC) - timedelta(days=2)

        def export(url: str) -> MagicMock:
            return _mock_response(200, body={"data": [{"id": "inc_1", "created_at": "2026-07-14T00:00:00Z"}]})

        session = FakeSession(
            _standard_handler(teams=[{"id": "t1"}], endpoint_responses={"/v3/incidents/export": export})
        )
        batches = _run_get_rows(
            session,
            "incidents",
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert batches == [[{"id": "inc_1", "created_at": "2026-07-14T00:00:00Z", "team_id": "t1"}]]
        export_calls = session.calls_to("/v3/incidents/export")
        assert len(export_calls) == 1
        params = _params(export_calls[0][0])
        assert params["type"] == "json"
        assert params["owner_id"] == "t1"
        assert params["start_time"] == last_value.strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_full_refresh_starts_at_epoch_and_chunks_windows(self) -> None:
        session = FakeSession(
            _standard_handler(
                teams=[{"id": "t1"}],
                endpoint_responses={"/v3/incidents/export": lambda url: _mock_response(200, body={"data": []})},
            )
        )
        _run_get_rows(session, "incidents")

        export_calls = session.calls_to("/v3/incidents/export")
        assert len(export_calls) > 1  # chunked into bounded windows, not one giant request
        first_params = _params(export_calls[0][0])
        assert first_params["start_time"] == FULL_REFRESH_START.strftime("%Y-%m-%dT%H:%M:%SZ")
        # Windows are contiguous: each start is the previous end.
        second_params = _params(export_calls[1][0])
        assert second_params["start_time"] == first_params["end_time"]

    def test_resume_cursor_overrides_window_start(self) -> None:
        manager = FakeResumableManager(resume_state=SquadcastResumeConfig(team_id="t1", cursor="2026-07-01T00:00:00Z"))
        session = FakeSession(
            _standard_handler(
                teams=[{"id": "t1"}],
                endpoint_responses={"/v3/incidents/export": lambda url: _mock_response(200, body={"data": []})},
            )
        )
        _run_get_rows(session, "incidents", manager)

        first_params = _params(session.calls_to("/v3/incidents/export")[0][0])
        assert first_params["start_time"] == "2026-07-01T00:00:00Z"

    def test_bare_list_export_body_is_accepted(self) -> None:
        last_value = datetime.now(UTC) - timedelta(days=1)
        session = FakeSession(
            _standard_handler(
                teams=[{"id": "t1"}],
                endpoint_responses={"/v3/incidents/export": lambda url: _mock_response(200, body=[{"id": "inc_1"}])},
            )
        )
        batches = _run_get_rows(
            session,
            "incidents",
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert batches == [[{"id": "inc_1", "team_id": "t1"}]]


class TestPostmortems:
    def test_windows_from_last_value_and_extracts_result_rows(self) -> None:
        last_value = datetime(2026, 6, 1, tzinfo=UTC)

        def postmortems(url: str) -> MagicMock:
            params = _params(url)
            assert params["fromDate"] == "2026-06-01T00:00:00Z"
            assert params["owner_id"] == "t1"
            body = {"data": [{"result": [{"id": "pm_1"}], "total_count": [{"count": 1}]}]}
            return _mock_response(200, body=body)

        session = FakeSession(
            _standard_handler(teams=[{"id": "t1"}], endpoint_responses={"/v3/incidents/postmortem": postmortems})
        )
        batches = _run_get_rows(
            session,
            "postmortems",
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert batches == [[{"id": "pm_1", "team_id": "t1"}]]

    def test_truncation_is_logged(self) -> None:
        body = {"data": [{"result": [{"id": "pm_1"}], "total_count": [{"count": 50}]}]}
        session = FakeSession(
            _standard_handler(
                teams=[{"id": "t1"}],
                endpoint_responses={"/v3/incidents/postmortem": lambda url: _mock_response(200, body=body)},
            )
        )
        logger = MagicMock()
        with patch(f"{SQUADCAST_MODULE}.make_tracked_session", return_value=session):
            list(get_rows("refresh_tok", "us", "postmortems", logger, FakeResumableManager()))  # type: ignore[arg-type]

        assert logger.warning.called
        assert "truncated" in logger.warning.call_args.args[0]


class TestEscalationPolicies:
    def test_reported_total_above_returned_rows_is_logged(self) -> None:
        body = {"data": [{"id": "ep_1"}], "meta": {"total_count": 10}}
        session = FakeSession(
            _standard_handler(
                teams=[{"id": "t1"}],
                endpoint_responses={"/v3/escalation-policies": lambda url: _mock_response(200, body=body)},
            )
        )
        logger = MagicMock()
        with patch(f"{SQUADCAST_MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("refresh_tok", "us", "escalation_policies", logger, FakeResumableManager()))  # type: ignore[arg-type]

        assert batches == [[{"id": "ep_1", "team_id": "t1"}]]
        assert logger.warning.called


class TestSquadcastSourceResponse:
    def test_incidents_partitioned_on_created_at_with_desc_watermark(self) -> None:
        response = squadcast_source("tok", "us", "incidents", MagicMock(), MagicMock())
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "desc"

    def test_full_refresh_endpoint_has_no_partition_settings(self) -> None:
        response = squadcast_source("tok", "us", "users", MagicMock(), MagicMock())
        assert response.partition_keys is None
        assert response.partition_mode is None
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize("endpoint", list(SQUADCAST_ENDPOINTS.keys()))
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = squadcast_source("tok", "us", endpoint, MagicMock(), MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == [SQUADCAST_ENDPOINTS[endpoint].primary_key]
        assert callable(response.items)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "probe_status,expected_ok,expected_status",
        [
            (200, True, 200),
            (401, False, 401),
            (403, False, 403),
            (500, False, 500),
        ],
    )
    def test_probe_status_mapping(self, probe_status: int, expected_ok: bool, expected_status: int) -> None:
        def handler(url: str, headers: dict[str, str]) -> MagicMock:
            if "/oauth/access-token" in url:
                return _mock_response(200, body=_auth_body())
            return _mock_response(probe_status, body={"meta": {"status": probe_status, "error_message": "boom"}})

        session = FakeSession(handler)
        with patch(f"{SQUADCAST_MODULE}.make_tracked_session", return_value=session):
            ok, status, _error = validate_credentials("tok", "us")

        assert ok is expected_ok
        assert status == expected_status

    @pytest.mark.parametrize("auth_status", [400, 401])
    def test_rejected_refresh_token(self, auth_status: int) -> None:
        session = FakeSession(lambda url, headers: _mock_response(auth_status, text="nope"))
        with patch(f"{SQUADCAST_MODULE}.make_tracked_session", return_value=session):
            ok, status, error = validate_credentials("tok", "us")

        assert ok is False
        assert status == 401
        assert error == "Invalid Squadcast refresh token"

    def test_transport_failure_returns_zero_status(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("no network")
        with patch(f"{SQUADCAST_MODULE}.make_tracked_session", return_value=session):
            ok, status, error = validate_credentials("tok", "us")

        assert ok is False
        assert status == 0
        assert error == "no network"

    def test_org_level_schema_probes_its_own_path(self) -> None:
        session = FakeSession(
            lambda url, headers: (
                _mock_response(200, body=_auth_body())
                if "/oauth/access-token" in url
                else _mock_response(200, body={"data": []})
            )
        )
        with patch(f"{SQUADCAST_MODULE}.make_tracked_session", return_value=session):
            validate_credentials("tok", "us", endpoint="users")

        assert len(session.calls_to("/v3/users")) == 1

    def test_team_scoped_schema_probes_teams(self) -> None:
        session = FakeSession(
            lambda url, headers: (
                _mock_response(200, body=_auth_body())
                if "/oauth/access-token" in url
                else _mock_response(200, body={"data": []})
            )
        )
        with patch(f"{SQUADCAST_MODULE}.make_tracked_session", return_value=session):
            validate_credentials("tok", "us", endpoint="incidents")

        assert len(session.calls_to("/v3/teams")) == 1
