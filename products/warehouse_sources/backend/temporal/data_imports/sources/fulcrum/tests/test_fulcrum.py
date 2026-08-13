import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.fulcrum import (
    FulcrumPageNumberPaginator,
    FulcrumResumeConfig,
    _to_epoch_seconds,
    fulcrum_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.settings import FULCRUM_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the fulcrum module.
FULCRUM_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.fulcrum.make_tracked_session"
)


def _response(
    data_key: str,
    items: list[dict[str, Any]] | None,
    *,
    total_pages: int | None = None,
    current_page: int | None = None,
    status: int = 200,
    drop_key: bool = False,
    body_override: dict[str, Any] | None = None,
) -> Response:
    body: dict[str, Any] = {}
    if not drop_key:
        body[data_key] = items or []
    if total_pages is not None:
        body["total_pages"] = total_pages
    if current_page is not None:
        body["current_page"] = current_page
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body if body_override is None else body_override).encode()
    return resp


def _make_manager(resume_state: FulcrumResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return fulcrum_source("token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


class TestToEpochSeconds:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 1, 1, tzinfo=UTC), 1609459200),
            ("date", date(2021, 1, 1), 1609459200),
            ("int_passthrough", 1609459200, 1609459200),
            ("iso_string", "2021-01-01T00:00:00+00:00", 1609459200),
            ("iso_string_z", "2021-01-01T00:00:00Z", 1609459200),
            ("none", None, None),
            ("garbage_string", "not-a-date", None),
        ]
    )
    def test_to_epoch_seconds(self, _name: str, value: Any, expected: int | None) -> None:
        assert _to_epoch_seconds(value) == expected


class TestIncrementalParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_records_incremental_adds_updated_since(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response("records", [{"id": "1"}], total_pages=1, current_page=1)])

        _rows(
            _source(
                "records",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
            )
        )

        # updated_since is the epoch-seconds cutoff; per_page and page ride alongside it.
        assert params[0]["updated_since"] == 1609459200
        assert params[0]["page"] == 1
        assert params[0]["per_page"] == FULCRUM_ENDPOINTS["records"].page_size

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_records_full_refresh_omits_filter(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response("records", [{"id": "1"}], total_pages=1, current_page=1)])

        _rows(
            _source(
                "records",
                _make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
            )
        )

        assert "updated_since" not in params[0]

    @parameterized.expand(["forms", "projects", "photos"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_incremental_endpoints_never_filter(self, endpoint: str, MockSession) -> None:
        # A full-refresh endpoint must never send updated_since even when a watermark is present —
        # it has no server-side time filter, so the incremental config is not wired for it.
        session = MockSession.return_value
        params = _wire(
            session, [_response(FULCRUM_ENDPOINTS[endpoint].data_key, [{"id": "1"}], total_pages=1, current_page=1)]
        )

        _rows(
            _source(
                endpoint,
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
            )
        )

        assert "updated_since" not in params[0]


class TestPaginatorHeuristic:
    def _body(self, total_pages: int | None = None, current_page: int | None = None) -> Response:
        body: dict[str, Any] = {}
        if total_pages is not None:
            body["total_pages"] = total_pages
        if current_page is not None:
            body["current_page"] = current_page
        resp = Response()
        resp.status_code = 200
        resp._content = json.dumps(body).encode()
        return resp

    @parameterized.expand(
        [
            # (total_pages, current_page, items_len, expected_more)
            ("more_by_total_pages", 3, 1, 1, True),
            ("last_by_total_pages", 3, 3, 1, False),
            ("missing_total_full_page_means_more", None, None, 2, True),
            ("missing_total_short_page_means_done", None, None, 1, False),
        ]
    )
    def test_update_state(
        self, _name: str, total_pages: int | None, current_page: int | None, items_len: int, expected_more: bool
    ) -> None:
        # per_page=2 so a 2-item page is "full" and a 1-item page is "short".
        paginator = FulcrumPageNumberPaginator(per_page=2)
        data: list[dict[str, Any]] = [{}] * items_len
        paginator.update_state(self._body(total_pages, current_page), data=data)
        assert paginator.has_next_page is expected_more
        # The page advances only while more pages remain.
        assert paginator.page == (2 if expected_more else 1)

    def test_empty_page_stops(self) -> None:
        paginator = FulcrumPageNumberPaginator(per_page=2)
        paginator.update_state(self._body(total_pages=5, current_page=1), data=[])
        assert paginator.has_next_page is False


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_yields_each_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response("forms", [{"id": "1"}], total_pages=2, current_page=1),
                _response("forms", [{"id": "2"}], total_pages=2, current_page=2),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("forms", manager))

        assert [r["id"] for r in rows] == ["1", "2"]
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2
        # One checkpoint saved after the first page (pointing at page 2); the last page saves nothing.
        manager.save_state.assert_called_once_with(FulcrumResumeConfig(page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("forms", [], total_pages=1, current_page=1)])

        manager = _make_manager()
        rows = _rows(_source("forms", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_without_total_stops(self, MockSession) -> None:
        # No total_pages in the body and a page shorter than per_page ends the sync in one request.
        session = MockSession.return_value
        _wire(session, [_response("forms", [{"id": "a"}, {"id": "b"}])])

        manager = _make_manager()
        rows = _rows(_source("forms", manager))

        assert [r["id"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response("forms", [{"id": "2"}], total_pages=2, current_page=2)])

        manager = _make_manager(FulcrumResumeConfig(page=2))
        _rows(_source("forms", manager))

        assert params[0]["page"] == 2
        assert session.send.call_count == 1


class TestFulcrumSource:
    @parameterized.expand(
        [
            ("records", ["id"], "created_at", "asc"),
            ("photos", ["access_key"], "created_at", "asc"),
            ("roles", ["id"], None, "asc"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(
        self, endpoint: str, expected_pk: list[str], partition_key: str | None, sort_mode: str, MockSession
    ) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == sort_mode
        if partition_key is None:
            assert response.partition_mode is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == [partition_key]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)
        with mock.patch(FULCRUM_SESSION_PATCH, return_value=session):
            assert validate_credentials("token") is expected

    def test_network_error_is_false(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(FULCRUM_SESSION_PATCH, return_value=session):
            assert validate_credentials("token") is False


class TestRetryAndErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch("time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status_code: int, MockSession, _sleep) -> None:
        # Fulcrum enforces an hourly request cap (429) and can 5xx transiently; both are retried by
        # the shared client on status, so a rate limit doesn't hard-fail the whole sync.
        session = MockSession.return_value
        transient = _response("forms", [], status=status_code, body_override={"error": "transient"})
        ok = _response("forms", [{"id": "1"}], total_pages=1, current_page=1)
        _wire(session, [transient, ok])

        rows = _rows(_source("forms", _make_manager()))

        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_fails_loud(self, MockSession) -> None:
        # A 401 is a permanent credential failure — it must surface as an HTTPError, not be retried.
        session = MockSession.return_value
        resp = _response("forms", [], status=401, body_override={"error": "unauthorized"})
        resp.url = "https://api.fulcrumapp.com/api/v2/forms.json"
        _wire(session, [resp])

        with pytest.raises(HTTPError):
            _rows(_source("forms", _make_manager()))
