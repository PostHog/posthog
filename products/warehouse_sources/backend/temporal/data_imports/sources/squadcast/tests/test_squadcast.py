import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import pytest
from unittest.mock import MagicMock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.squadcast import (
    SquadcastSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.squadcast.settings import SQUADCAST_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.squadcast.source import SquadcastSource
from products.warehouse_sources.backend.temporal.data_imports.sources.squadcast.squadcast import (
    FULL_REFRESH_START,
    PAGE_SIZE,
    SquadcastAuthError,
    SquadcastResumeConfig,
    validate_credentials,
)

Handler = Callable[[RecordedRequest], ScriptedResponse]


def _json(body: Any = None, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body if body is not None else {})


def _auth_body(expires_in_seconds: float = 3600) -> dict[str, Any]:
    return {"data": {"access_token": "jwt_abc", "expires_at": time.time() + expires_in_seconds}}


def _params(request: RecordedRequest) -> dict[str, str]:
    return {key: values[0] for key, values in request.query.items()}


def _calls_to(requests_made: list[RecordedRequest], path: str) -> list[RecordedRequest]:
    return [request for request in requests_made if request.path == path]


def _standard_handler(
    teams: list[dict[str, Any]],
    endpoint_responses: dict[str, Handler],
    auth_expires_in: float = 3600,
) -> Handler:
    """Dispatches by path so tests don't depend on exact request ordering."""

    def handler(request: RecordedRequest) -> ScriptedResponse:
        path = request.path
        if path == "/oauth/access-token":
            return _json(_auth_body(auth_expires_in))
        if path == "/v3/teams" and "/v3/teams" not in endpoint_responses:
            return _json({"data": teams})
        if path in endpoint_responses:
            return endpoint_responses[path](request)
        raise AssertionError(f"unexpected request: {request.url}")

    return handler


def _run(
    endpoint: str,
    script: Script,
    resume_state: SquadcastResumeConfig | None = None,
    region: Literal["us", "eu"] = "us",
    **inputs: Any,
) -> DriveResult:
    config = SquadcastSourceConfig(refresh_token="refresh_tok", region=region)
    return SourceDriver(SquadcastSource(), config).run(endpoint, script, resume_state=resume_state, **inputs)


class TestAuth:
    def test_bearer_token_from_refresh_exchange_is_sent_to_api(self) -> None:
        result = _run(
            "users",
            _standard_handler(
                teams=[], endpoint_responses={"/v3/users": lambda request: _json({"data": [{"id": "u1"}]})}
            ),
        )

        assert result.items == [[{"id": "u1"}]]
        auth_calls = _calls_to(result.requests, "/oauth/access-token")
        assert auth_calls[0].headers["x-refresh-token"] == "refresh_tok"
        user_calls = _calls_to(result.requests, "/v3/users")
        assert user_calls[0].headers["authorization"] == "Bearer jwt_abc"

    def test_access_token_reused_while_valid(self) -> None:
        result = _run(
            "services",
            _standard_handler(
                teams=[{"id": "t1"}, {"id": "t2"}],
                endpoint_responses={"/v3/services": lambda request: _json({"data": [{"id": "s"}]})},
            ),
        )

        assert len(_calls_to(result.requests, "/oauth/access-token")) == 1

    def test_expired_access_token_is_re_exchanged(self) -> None:
        # expires_at in the past forces a re-exchange before every API request.
        result = _run(
            "services",
            _standard_handler(
                teams=[{"id": "t1"}],
                endpoint_responses={"/v3/services": lambda request: _json({"data": [{"id": "s"}]})},
                auth_expires_in=-100,
            ),
        )

        # One exchange per API request (teams + services).
        assert len(_calls_to(result.requests, "/oauth/access-token")) == 2

    def test_rejected_refresh_token_raises_auth_error(self) -> None:
        result = _run(
            "users", always(_json({"meta": {"status": 401, "error_message": "invalid token"}}, status_code=401))
        )

        assert isinstance(result.raised, SquadcastAuthError)
        assert "Squadcast refresh token was rejected" in str(result.raised)

    def test_eu_region_uses_eu_hosts(self) -> None:
        def handler(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/access-token":
                return _json(_auth_body())
            return _json({"data": []})

        result = _run("users", handler, region="eu")

        assert result.urls[0].startswith("https://auth.eu.squadcast.com/")
        assert result.urls[1].startswith("https://api.eu.squadcast.com/")


class TestCredentialHardening:
    # The refresh token is long-lived: dropping redaction would persist it via HTTP sample
    # capture, and following redirects would replay credentialed headers to the target.
    def _assert_hardened(self, session_options: list[dict[str, Any]]) -> None:
        assert session_options
        for options in session_options:
            assert options["redact_values"] == ("refresh_tok",)
            assert options["allow_redirects"] is False
            # Every session is excluded from sample capture: the token exchange response carries
            # the minted tokens, and the API responses carry arbitrary customer-authored
            # operational data (incidents, postmortems, runbooks) the scrubbers can't recognise.
            assert options["capture"] is False

    def test_sync_sessions_are_hardened(self) -> None:
        result = _run(
            "users",
            _standard_handler(
                teams=[], endpoint_responses={"/v3/users": lambda request: _json({"data": [{"id": "u1"}]})}
            ),
        )

        self._assert_hardened(result.session_options)

    def test_validate_credentials_sessions_are_hardened(self) -> None:
        def handler(request: RecordedRequest) -> ScriptedResponse:
            return _json(_auth_body()) if request.path == "/oauth/access-token" else _json({"data": []})

        with scripted_network(handler) as network:
            validate_credentials("refresh_tok", "us")

        self._assert_hardened(network.session_options)


class TestTeamFanOut:
    def test_rows_fetched_per_team_and_stamped_with_team_id(self) -> None:
        def services(request: RecordedRequest) -> ScriptedResponse:
            team = _params(request)["owner_id"]
            return _json({"data": [{"id": f"svc_{team}"}]})

        result = _run(
            "services",
            _standard_handler(teams=[{"id": "t1"}, {"id": "t2"}], endpoint_responses={"/v3/services": services}),
        )

        assert result.items == [
            [{"id": "svc_t1", "team_id": "t1"}],
            [{"id": "svc_t2", "team_id": "t2"}],
        ]

    def test_services_api_key_never_reaches_yielded_rows(self) -> None:
        # The services payload carries the live key alert sources use to send events;
        # syncing it would expose it to anyone who can read the warehouse table.
        def services(request: RecordedRequest) -> ScriptedResponse:
            return _json({"data": [{"id": "svc_1", "api_key": "sq_live_key", "name": "checkout"}]})

        result = _run(
            "services", _standard_handler(teams=[{"id": "t1"}], endpoint_responses={"/v3/services": services})
        )

        assert result.items == [[{"id": "svc_1", "name": "checkout", "team_id": "t1"}]]

    def test_team_without_access_is_skipped(self) -> None:
        def services(request: RecordedRequest) -> ScriptedResponse:
            team = _params(request)["owner_id"]
            if team == "t2":
                return _json({"error": "forbidden"}, status_code=403)
            return _json({"data": [{"id": f"svc_{team}"}]})

        result = _run(
            "services",
            _standard_handler(
                teams=[{"id": "t1"}, {"id": "t2"}, {"id": "t3"}], endpoint_responses={"/v3/services": services}
            ),
        )

        assert [batch[0]["id"] for batch in result.items] == ["svc_t1", "svc_t3"]

    def test_non_permission_error_fails_the_sync(self) -> None:
        result = _run(
            "services",
            _standard_handler(
                teams=[{"id": "t1"}],
                endpoint_responses={"/v3/services": lambda request: _json({"error": "bad request"}, status_code=400)},
            ),
        )

        assert isinstance(result.raised, requests.HTTPError)

    def test_team_bookmark_saved_between_teams(self) -> None:
        result = _run(
            "services",
            _standard_handler(
                teams=[{"id": "t1"}, {"id": "t2"}],
                endpoint_responses={"/v3/services": lambda request: _json({"data": [{"id": "s"}]})},
            ),
        )

        assert [(s.team_id, s.cursor) for s in result.saved_states] == [("t2", None)]

    def test_resume_skips_completed_teams(self) -> None:
        def services(request: RecordedRequest) -> ScriptedResponse:
            return _json({"data": [{"id": f"svc_{_params(request)['owner_id']}"}]})

        result = _run(
            "services",
            _standard_handler(
                teams=[{"id": "t1"}, {"id": "t2"}, {"id": "t3"}], endpoint_responses={"/v3/services": services}
            ),
            resume_state=SquadcastResumeConfig(team_id="t2", cursor=None),
        )

        assert [batch[0]["id"] for batch in result.items] == ["svc_t2", "svc_t3"]

    def test_resume_with_missing_team_starts_over(self) -> None:
        def services(request: RecordedRequest) -> ScriptedResponse:
            return _json({"data": [{"id": f"svc_{_params(request)['owner_id']}"}]})

        result = _run(
            "services",
            _standard_handler(teams=[{"id": "t1"}], endpoint_responses={"/v3/services": services}),
            resume_state=SquadcastResumeConfig(team_id="gone", cursor=None),
        )

        assert [batch[0]["id"] for batch in result.items] == ["svc_t1"]


class TestOffsetPagination:
    def test_paginates_slos_and_saves_state_after_yield(self) -> None:
        full_page = [{"id": i} for i in range(PAGE_SIZE)]

        def slos(request: RecordedRequest) -> ScriptedResponse:
            offset = int(_params(request)["offset"])
            return _json({"data": {"slos": full_page if offset == 0 else [{"id": "last"}]}})

        result = _run("slos", _standard_handler(teams=[{"id": "t1"}], endpoint_responses={"/v3/slo": slos}))

        assert len(result.items) == 2
        assert len(result.items[0]) == PAGE_SIZE
        assert result.items[1][0]["id"] == "last"
        assert [(s.team_id, s.cursor) for s in result.saved_states] == [("t1", str(PAGE_SIZE))]

    def test_resumes_from_saved_offset(self) -> None:
        def slos(request: RecordedRequest) -> ScriptedResponse:
            assert _params(request)["offset"] == str(PAGE_SIZE)
            return _json({"data": {"slos": [{"id": "x"}]}})

        result = _run(
            "slos",
            _standard_handler(teams=[{"id": "t1"}], endpoint_responses={"/v3/slo": slos}),
            resume_state=SquadcastResumeConfig(team_id="t1", cursor=str(PAGE_SIZE)),
        )

        assert result.items == [[{"id": "x", "team_id": "t1"}]]


class TestCursorPagination:
    def test_follows_next_cursor_until_has_next_is_false(self) -> None:
        def schedules(request: RecordedRequest) -> ScriptedResponse:
            params = _params(request)
            assert params["teamID"] == "t1"
            if "cursor" not in params:
                return _json(
                    {"data": [{"id": 1}], "pageInfo": {"hasNext": True, "nextCursor": "cur_2", "hasPrev": False}}
                )
            assert params["cursor"] == "cur_2"
            return _json({"data": [{"id": 2}], "pageInfo": {"hasNext": False, "hasPrev": True}})

        result = _run(
            "schedules", _standard_handler(teams=[{"id": "t1"}], endpoint_responses={"/v4/schedules": schedules})
        )

        assert [batch[0]["id"] for batch in result.items] == [1, 2]
        assert [(s.team_id, s.cursor) for s in result.saved_states] == [("t1", "cur_2")]


class TestIncidentExport:
    def test_incremental_windows_start_at_last_value(self) -> None:
        last_value = datetime.now(UTC) - timedelta(days=2)

        def export(request: RecordedRequest) -> ScriptedResponse:
            return _json({"data": [{"id": "inc_1", "created_at": "2026-07-14T00:00:00Z"}]})

        result = _run(
            "incidents",
            _standard_handler(teams=[{"id": "t1"}], endpoint_responses={"/v3/incidents/export": export}),
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.items == [[{"id": "inc_1", "created_at": "2026-07-14T00:00:00Z", "team_id": "t1"}]]
        export_calls = _calls_to(result.requests, "/v3/incidents/export")
        assert len(export_calls) == 1
        params = _params(export_calls[0])
        assert params["type"] == "json"
        assert params["owner_id"] == "t1"
        assert params["start_time"] == last_value.strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_full_refresh_starts_at_epoch_and_chunks_windows(self) -> None:
        result = _run(
            "incidents",
            _standard_handler(
                teams=[{"id": "t1"}],
                endpoint_responses={"/v3/incidents/export": lambda request: _json({"data": []})},
            ),
        )

        export_calls = _calls_to(result.requests, "/v3/incidents/export")
        assert len(export_calls) > 1  # chunked into bounded windows, not one giant request
        first_params = _params(export_calls[0])
        assert first_params["start_time"] == FULL_REFRESH_START.strftime("%Y-%m-%dT%H:%M:%SZ")
        # Windows are contiguous: each start is the previous end.
        second_params = _params(export_calls[1])
        assert second_params["start_time"] == first_params["end_time"]

    def test_resume_cursor_overrides_window_start(self) -> None:
        result = _run(
            "incidents",
            _standard_handler(
                teams=[{"id": "t1"}],
                endpoint_responses={"/v3/incidents/export": lambda request: _json({"data": []})},
            ),
            resume_state=SquadcastResumeConfig(team_id="t1", cursor="2026-07-01T00:00:00Z"),
        )

        first_params = _params(_calls_to(result.requests, "/v3/incidents/export")[0])
        assert first_params["start_time"] == "2026-07-01T00:00:00Z"

    def test_bare_list_export_body_is_accepted(self) -> None:
        last_value = datetime.now(UTC) - timedelta(days=1)

        result = _run(
            "incidents",
            _standard_handler(
                teams=[{"id": "t1"}],
                endpoint_responses={"/v3/incidents/export": lambda request: _json([{"id": "inc_1"}])},
            ),
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.items == [[{"id": "inc_1", "team_id": "t1"}]]


class TestPostmortems:
    def test_windows_from_last_value_and_extracts_result_rows(self) -> None:
        last_value = datetime(2026, 6, 1, tzinfo=UTC)

        def postmortems(request: RecordedRequest) -> ScriptedResponse:
            params = _params(request)
            assert params["fromDate"] == "2026-06-01T00:00:00Z"
            assert params["owner_id"] == "t1"
            return _json({"data": [{"result": [{"id": "pm_1"}], "total_count": [{"count": 1}]}]})

        result = _run(
            "postmortems",
            _standard_handler(teams=[{"id": "t1"}], endpoint_responses={"/v3/incidents/postmortem": postmortems}),
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )

        assert result.items == [[{"id": "pm_1", "team_id": "t1"}]]

    def test_truncation_is_logged(self) -> None:
        body = {"data": [{"result": [{"id": "pm_1"}], "total_count": [{"count": 50}]}]}
        logger = MagicMock()

        _run(
            "postmortems",
            _standard_handler(
                teams=[{"id": "t1"}],
                endpoint_responses={"/v3/incidents/postmortem": lambda request: _json(body)},
            ),
            logger=logger,
        )

        assert logger.warning.called
        assert "truncated" in logger.warning.call_args.args[0]


class TestUnpaginatedTeamEndpoints:
    @pytest.mark.parametrize(
        "endpoint,path,body,expect_warning",
        [
            (
                "escalation_policies",
                "/v3/escalation-policies",
                {"data": [{"id": "r1"}], "meta": {"total_count": 10}},
                True,
            ),
            (
                "escalation_policies",
                "/v3/escalation-policies",
                {"data": [{"id": "r1"}], "meta": {"total_count": 1}},
                False,
            ),
            ("squads", "/v4/squads", {"data": [{"id": "r1"}], "pageInfo": {"hasNext": True, "hasPrev": False}}, True),
            ("squads", "/v4/squads", {"data": [{"id": "r1"}], "pageInfo": {"hasNext": False, "hasPrev": False}}, False),
            ("squads", "/v4/squads", {"data": [{"id": "r1"}]}, False),
        ],
    )
    def test_possible_truncation_is_logged(
        self, endpoint: str, path: str, body: dict[str, Any], expect_warning: bool
    ) -> None:
        def handler(request: RecordedRequest) -> ScriptedResponse:
            team_param = SQUADCAST_ENDPOINTS[endpoint].team_param
            assert team_param is not None
            assert _params(request) == {team_param: "t1"}
            return _json(body)

        logger = MagicMock()

        result = _run(
            endpoint,
            _standard_handler(teams=[{"id": "t1"}], endpoint_responses={path: handler}),
            logger=logger,
        )

        assert result.items == [[{"id": "r1", "team_id": "t1"}]]
        assert logger.warning.called is expect_warning


def _schedules_handler(pages: dict[str | None, dict[str, Any]]) -> Handler:
    def handler(request: RecordedRequest) -> ScriptedResponse:
        params = _params(request)
        assert params["teamID"] == "t1"
        assert params["pageSize"] == str(PAGE_SIZE)
        return _json(pages[params.get("cursor")])

    return handler


def _constant(response: ScriptedResponse) -> Handler:
    return lambda request: response


class TestScheduleRotations:
    def _endpoint_responses(
        self, pages: dict[str | None, dict[str, Any]], rotations: dict[str, ScriptedResponse]
    ) -> dict[str, Handler]:
        responses: dict[str, Handler] = {"/v4/schedules": _schedules_handler(pages)}
        for schedule_id, response in rotations.items():
            responses[f"/v4/schedules/{schedule_id}/rotations"] = _constant(response)
        return responses

    def test_walks_schedule_pages_and_stages_current_page_cursor(self) -> None:
        pages: dict[str | None, dict[str, Any]] = {
            None: {"data": [{"id": 1}, {"id": 2}], "pageInfo": {"hasNext": True, "nextCursor": "cur_2"}},
            "cur_2": {"data": [{"id": 3}], "pageInfo": {"hasNext": False}},
        }
        rotations = {
            "1": _json({"data": [{"id": 10, "scheduleID": 1}, {"id": 11, "scheduleID": 1}]}),
            "2": _json({"data": None}),
            "3": _json({"data": [{"id": 10, "scheduleID": 3}]}),
        }

        result = _run(
            "schedule_rotations",
            _standard_handler(teams=[{"id": "t1"}], endpoint_responses=self._endpoint_responses(pages, rotations)),
        )

        assert result.items == [
            [{"id": 10, "scheduleID": 1, "team_id": "t1"}, {"id": 11, "scheduleID": 1, "team_id": "t1"}],
            [{"id": 10, "scheduleID": 3, "team_id": "t1"}],
        ]
        # The cursor staged before each page's rows points at that page, so a resume re-reads
        # the page instead of skipping its remaining schedules.
        assert [(s.team_id, s.cursor) for s in result.saved_states] == [("t1", None), ("t1", "cur_2")]
        assert result.response is not None
        assert result.response.primary_keys == ["scheduleID", "id"]

    def test_resumes_from_saved_schedules_cursor(self) -> None:
        pages: dict[str | None, dict[str, Any]] = {"cur_2": {"data": [{"id": 3}], "pageInfo": {"hasNext": False}}}
        rotations = {"3": _json({"data": [{"id": 30, "scheduleID": 3}]})}

        result = _run(
            "schedule_rotations",
            _standard_handler(teams=[{"id": "t1"}], endpoint_responses=self._endpoint_responses(pages, rotations)),
            resume_state=SquadcastResumeConfig(team_id="t1", cursor="cur_2"),
        )

        assert result.items == [[{"id": 30, "scheduleID": 3, "team_id": "t1"}]]

    @pytest.mark.parametrize(
        "failing_status,expect_raised",
        [
            (404, False),
            (403, False),
            (400, True),
        ],
    )
    def test_rotation_fetch_error_for_one_schedule(self, failing_status: int, expect_raised: bool) -> None:
        pages: dict[str | None, dict[str, Any]] = {
            None: {"data": [{"id": 1}, {"id": 2}], "pageInfo": {"hasNext": False}},
        }
        rotations = {
            "1": _json({"error": {"code": "x", "message": "boom"}}, status_code=failing_status),
            "2": _json({"data": [{"id": 20}]}),
        }

        result = _run(
            "schedule_rotations",
            _standard_handler(teams=[{"id": "t1"}], endpoint_responses=self._endpoint_responses(pages, rotations)),
        )

        if expect_raised:
            assert isinstance(result.raised, requests.HTTPError)
            assert result.items == []
        else:
            assert result.raised is None
            assert result.items == [[{"id": 20, "scheduleID": 2, "team_id": "t1"}]]


class TestSquadcastSourceResponse:
    def test_incidents_partitioned_on_created_at_with_desc_watermark(self) -> None:
        response = _run("incidents", always(_json({"data": []}))).response
        assert response is not None
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "desc"

    def test_full_refresh_endpoint_has_no_partition_settings(self) -> None:
        response = _run("users", always(_json({"data": []}))).response
        assert response is not None
        assert response.partition_keys is None
        assert response.partition_mode is None
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize("endpoint", list(SQUADCAST_ENDPOINTS.keys()))
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = _run(endpoint, always(_json({"data": []}))).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == list(SQUADCAST_ENDPOINTS[endpoint].primary_keys)
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
        def handler(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/access-token":
                return _json(_auth_body())
            return _json({"meta": {"status": probe_status, "error_message": "boom"}}, status_code=probe_status)

        with scripted_network(handler):
            ok, status, _error = validate_credentials("tok", "us")

        assert ok is expected_ok
        assert status == expected_status

    @pytest.mark.parametrize("auth_status", [400, 401])
    def test_rejected_refresh_token(self, auth_status: int) -> None:
        with scripted_network(always(_json({"error": "nope"}, status_code=auth_status))):
            ok, status, error = validate_credentials("tok", "us")

        assert ok is False
        assert status == 401
        assert error == "Invalid Squadcast refresh token"

    def test_transport_failure_returns_zero_status(self) -> None:
        with scripted_network(always(ConnectionError("no network"))):
            ok, status, error = validate_credentials("tok", "us")

        assert ok is False
        assert status == 0
        assert error == (
            "HTTPSConnectionPool(host='auth.squadcast.com', port=443): Max retries exceeded"
            " with url: /oauth/access-token (Caused by ProtocolError('Connection aborted.',"
            " ConnectionError('no network')))"
        )

    def test_org_level_schema_probes_its_own_path(self) -> None:
        def handler(request: RecordedRequest) -> ScriptedResponse:
            return _json(_auth_body()) if request.path == "/oauth/access-token" else _json({"data": []})

        with scripted_network(handler) as network:
            validate_credentials("tok", "us", endpoint="users")

        assert len(_calls_to(network.requests_log, "/v3/users")) == 1

    def test_team_scoped_schema_probes_teams(self) -> None:
        def handler(request: RecordedRequest) -> ScriptedResponse:
            return _json(_auth_body()) if request.path == "/oauth/access-token" else _json({"data": []})

        with scripted_network(handler) as network:
            validate_credentials("tok", "us", endpoint="incidents")

        assert len(_calls_to(network.requests_log, "/v3/teams")) == 1
