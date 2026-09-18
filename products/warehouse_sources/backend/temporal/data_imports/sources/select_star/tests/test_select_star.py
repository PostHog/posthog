import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Optional, cast

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.select_star.select_star import (
    SelectStarResumeConfig,
    select_star_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.select_star.settings import (
    ENDPOINTS,
    SELECTSTAR_BASE_URL,
    SELECTSTAR_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the select_star module.
SELECT_STAR_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.select_star.select_star.make_tracked_session"
)

TABLES_URL = f"{SELECTSTAR_BASE_URL}/v1/tables/"
TAGS_URL = f"{SELECTSTAR_BASE_URL}/v1/tags/"


def _json_response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _page(results: list[dict[str, Any]], *, next_url: Optional[str] = None) -> Response:
    return _json_response({"count": len(results), "next": next_url, "previous": None, "results": results})


def _make_manager(resume_state: SelectStarResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's (url, params, auth) at send time."""
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> Any:
        snapshots.append({"url": request.url, "params": request.params, "auth": request.auth})
        # Return the request itself rather than a bare MagicMock: RESTClient now checks
        # `prepared.url` against the allowed-hosts pin before sending (see select_star.py's
        # `allowed_hosts`), and `urlsplit()` on an unconfigured MagicMock attribute raises
        # TypeError. A real `Request` carries a real `.url` string, matching the pattern used
        # by ably/conekta's tests for the same allowed-hosts-pinned client.
        return request

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in cast("Iterable[Any]", source_response.items()) for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_yields_and_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"guid": "ta_1"}, {"guid": "ta_2"}])])

        manager = _make_manager()
        rows = _rows(select_star_source("tok", "Tables", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == [{"guid": "ta_1"}, {"guid": "ta_2"}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_url_until_null(self, MockSession) -> None:
        session = MockSession.return_value
        second = f"{TABLES_URL}?page=2"
        snapshots = _wire(session, [_page([{"guid": "a"}], next_url=second), _page([{"guid": "b"}])])

        manager = _make_manager()
        rows = _rows(select_star_source("tok", "Tables", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == [{"guid": "a"}, {"guid": "b"}]
        assert snapshots[0]["url"] == TABLES_URL
        assert snapshots[1]["url"] == second
        manager.save_state.assert_called_once_with(SelectStarResumeConfig(next_url=second))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        second = f"{TABLES_URL}?page=2"
        snapshots = _wire(session, [_page([{"guid": "b"}])])

        manager = _make_manager(SelectStarResumeConfig(next_url=second))
        rows = _rows(select_star_source("tok", "Tables", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == [{"guid": "b"}]
        assert session.send.call_count == 1
        assert snapshots[0]["url"] == second

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([])])

        manager = _make_manager()
        rows = _rows(select_star_source("tok", "Tables", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == []
        manager.save_state.assert_not_called()


class TestAuth:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_uses_token_scheme_not_bearer(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_page([])])

        _rows(select_star_source("tok-123", "Tables", team_id=1, job_id="j", resumable_source_manager=_make_manager()))

        # Auth is applied by `requests` when the session actually prepares the request; assert on
        # the auth callable's effect directly rather than depending on that internal prepare step.
        prepared = mock.MagicMock()
        prepared.headers = {}
        snapshots[0]["auth"](prepared)
        assert prepared.headers["Authorization"] == "Token tok-123"


class TestIncrementalFilter:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_when_not_incremental(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_page([])])

        _rows(select_star_source("tok", "Tables", team_id=1, job_id="j", resumable_source_manager=_make_manager()))

        assert "updated_on__gte" not in snapshots[0]["params"]
        assert "last_queried_on__gte" not in snapshots[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_default_incremental_field_used_when_none_selected(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_page([])])

        _rows(
            select_star_source(
                "tok",
                "Tables",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["updated_on__gte"] == datetime(2026, 1, 1, tzinfo=UTC)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_honors_user_selected_incremental_field(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_page([])])

        _rows(
            select_star_source(
                "tok",
                "Tables",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="last_queried_on",
            )
        )

        assert "updated_on__gte" not in snapshots[0]["params"]
        assert snapshots[0]["params"]["last_queried_on__gte"] == datetime(2026, 1, 1, tzinfo=UTC)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_param_for_endpoint_without_incremental_fields(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_page([])])

        _rows(
            select_star_source(
                "tok",
                "Columns",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert not any(key.endswith("__gte") for key in snapshots[0]["params"])


class TestValidateCredentials:
    @mock.patch(SELECT_STAR_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("tok") == (True, None)

    @parameterized.expand(
        [
            ("unauthorized", 401),
            ("forbidden", 403),
            ("server_error", 500),
        ]
    )
    @mock.patch(SELECT_STAR_SESSION_PATCH)
    def test_status_mapping_is_a_failure(self, _name: str, status: int, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        ok, message = validate_credentials("tok")
        assert ok is False
        assert message

    def test_401_and_403_messages_differ(self) -> None:
        with mock.patch(SELECT_STAR_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
            _, unauthorized_message = validate_credentials("tok")
        with mock.patch(SELECT_STAR_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=403)
            _, forbidden_message = validate_credentials("tok")
        assert unauthorized_message != forbidden_message

    @mock.patch(SELECT_STAR_SESSION_PATCH)
    def test_connection_error_maps_to_generic_message(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        ok, message = validate_credentials("tok")
        assert ok is False
        assert message


class TestSelectStarSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        # Construction does no I/O (items is a lazy generator), so no session patch is needed.
        response = select_star_source("tok", endpoint, team_id=1, job_id="j", resumable_source_manager=mock.MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == ["guid"]
        assert response.sort_mode == "asc"

    def test_tables_and_dashboards_are_partitioned(self) -> None:
        for endpoint in ("Tables", "Dashboards"):
            response = select_star_source(
                "tok", endpoint, team_id=1, job_id="j", resumable_source_manager=mock.MagicMock()
            )
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [SELECTSTAR_ENDPOINTS[endpoint].partition_key]

    def test_endpoints_without_a_stable_created_field_are_not_partitioned(self) -> None:
        for endpoint in ("Columns", "Databases", "Schemas", "Tags"):
            response = select_star_source(
                "tok", endpoint, team_id=1, job_id="j", resumable_source_manager=mock.MagicMock()
            )
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_every_endpoint_uses_guid_primary_key(self) -> None:
        assert all(config.primary_keys == ["guid"] for config in SELECTSTAR_ENDPOINTS.values())
        assert set(SELECTSTAR_ENDPOINTS) == set(ENDPOINTS)
