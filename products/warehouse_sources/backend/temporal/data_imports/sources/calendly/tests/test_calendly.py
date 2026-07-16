import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.calendly import (
    CALENDLY_BASE_URL,
    CalendlyResumeConfig,
    _format_datetime,
    calendly_source,
    get_current_organization,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.settings import ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# The /users/me bootstrap and validate_credentials build their own tracked session in the calendly module.
CALENDLY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.calendly.calendly.make_tracked_session"
)

ORG_URI = "https://api.calendly.com/organizations/ABC123"


def _response(
    collection: Optional[list[dict[str, Any]]],
    next_page: Optional[str] = None,
    *,
    status: int = 200,
    drop_collection: bool = False,
) -> Response:
    body: dict[str, Any] = {"pagination": {"next_page": next_page}}
    if not drop_collection:
        body["collection"] = collection or []
    resp = Response()
    resp.status_code = status
    resp.url = f"{CALENDLY_BASE_URL}/event_types?count=100"
    resp._content = json.dumps(body).encode()
    return resp


def _users_me_response(status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = f"{CALENDLY_BASE_URL}/users/me"
    resp._content = json.dumps({"resource": {"current_organization": ORG_URI}}).encode()
    return resp


def _make_manager(resume_state: Optional[CalendlyResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's url/params AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "event_types", **kwargs):
    return calendly_source(
        token="token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000000Z"),
            ("string_passthrough", "2026-03-04T00:00:00.000000Z", "2026-03-04T00:00:00.000000Z"),
        ]
    )
    def test_format_datetime(self, _name: str, value: object, expected: str) -> None:
        assert _format_datetime(value) == expected

    def test_no_plus_zero_offset_in_output(self) -> None:
        assert "+00:00" not in _format_datetime(datetime(2026, 3, 4, tzinfo=UTC))


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(CALENDLY_SESSION_PATCH)
    def test_validate_credentials_status_mapping(
        self, _name: str, status_code: int, expected: bool, mock_session: mock.MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("token") is expected

    @mock.patch(CALENDLY_SESSION_PATCH, side_effect=Exception("network down"))
    def test_validate_credentials_swallows_exceptions(self, _mock_session: mock.MagicMock) -> None:
        assert validate_credentials("token") is False


class TestGetCurrentOrganization:
    @mock.patch(CALENDLY_SESSION_PATCH)
    def test_parses_org_uri(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _users_me_response()
        assert get_current_organization("token") == ORG_URI


class TestPagination:
    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_across_pages_following_next_page(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        next_url = f"{CALENDLY_BASE_URL}/event_types?page=2"
        snapshots = _wire(
            MockClientSession.return_value,
            [_response([{"uri": "a"}, {"uri": "b"}], next_page=next_url), _response([{"uri": "c"}])],
        )
        manager = _make_manager()

        rows = _rows(_source(manager))

        assert [r["uri"] for r in rows] == ["a", "b", "c"]
        # First request is the org-scoped list; second follows the self-contained next_page URL.
        assert snapshots[0]["params"]["count"] == 100
        assert snapshots[0]["params"]["organization"] == ORG_URI
        assert snapshots[1]["url"] == next_url
        assert snapshots[1]["params"] == {}
        # State saved after the first page yielded, pointing at page 2; no save at the end.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == CalendlyResumeConfig(next_url=next_url)

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_collection_yields_nothing(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        _wire(MockClientSession.return_value, [_response([])])

        rows = _rows(_source(_make_manager()))

        assert rows == []

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_collection_key_treated_as_empty(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        _wire(MockClientSession.return_value, [_response(None, drop_collection=True)])

        rows = _rows(_source(_make_manager()))

        assert rows == []

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_mid_pagination_does_not_terminate_early(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        # An empty page that still advertises a next_page must not end the sync.
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        _wire(
            MockClientSession.return_value,
            [_response([], next_page=f"{CALENDLY_BASE_URL}/event_types?page=2"), _response([{"uri": "a"}])],
        )

        rows = _rows(_source(_make_manager()))

        assert [r["uri"] for r in rows] == ["a"]

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_users_me_and_starts_from_saved_url(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        resume_url = f"{CALENDLY_BASE_URL}/event_types?page=5"
        snapshots = _wire(MockClientSession.return_value, [_response([{"uri": "z"}])])
        manager = _make_manager(resume_state=CalendlyResumeConfig(next_url=resume_url))

        rows = _rows(_source(manager))

        assert [r["uri"] for r in rows] == ["z"]
        # No /users/me bootstrap call on resume; first request is the saved URL.
        mock_calendly_session.assert_not_called()
        assert snapshots[0]["url"] == resume_url
        assert snapshots[0]["params"] == {}

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_request_scopes_to_organization(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        snapshots = _wire(MockClientSession.return_value, [_response([{"uri": "a"}])])

        _rows(_source(_make_manager()))

        # users/me bootstrap first, then the scoped list request carrying the org URI.
        users_me_call = mock_calendly_session.return_value.get.call_args
        assert users_me_call.args[0] == f"{CALENDLY_BASE_URL}/users/me"
        assert snapshots[0]["params"]["organization"] == ORG_URI

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_http_4xx_fails_loudly(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        _wire(MockClientSession.return_value, [_response([], status=401)])

        with pytest.raises(HTTPError, match="401 Client Error"):
            _rows(_source(_make_manager()))


class TestRequestParams:
    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_scheduled_events_adds_sort_and_no_filter_without_incremental(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        snapshots = _wire(MockClientSession.return_value, [_response([{"uri": "a"}])])

        _rows(_source(_make_manager(), endpoint="scheduled_events"))

        assert snapshots[0]["params"]["sort"] == "start_time:asc"
        assert "min_start_time" not in snapshots[0]["params"]

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_scheduled_events_adds_min_start_time_when_incremental(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        snapshots = _wire(MockClientSession.return_value, [_response([{"uri": "a"}])])

        _rows(
            _source(
                _make_manager(),
                endpoint="scheduled_events",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["min_start_time"] == "2026-01-01T00:00:00.000000Z"

    @mock.patch(CALENDLY_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_incremental_endpoint_never_adds_filter(
        self, MockClientSession: mock.MagicMock, mock_calendly_session: mock.MagicMock
    ) -> None:
        mock_calendly_session.return_value.get.return_value = _users_me_response()
        snapshots = _wire(MockClientSession.return_value, [_response([{"uri": "a"}])])

        _rows(
            _source(
                _make_manager(),
                endpoint="event_types",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert "min_start_time" not in snapshots[0]["params"]


class TestCalendlySource:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(_make_manager(), endpoint=endpoint)

        assert response.name == endpoint
        assert response.primary_keys == ["uri"]
        assert response.sort_mode == "asc"
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
