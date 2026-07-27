import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.salesloft import (
    SALESLOFT_BASE_URL,
    SalesloftResumeConfig,
    _build_params,
    _format_datetime,
    salesloft_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.settings import SALESLOFT_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the salesloft module.
SALESLOFT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.salesloft.make_tracked_session"
)


def _response(items: list[dict[str, Any]] | None, next_page: int | None, status: int = 200) -> Response:
    body: dict[str, Any] = {"data": items or [], "metadata": {"paging": {"per_page": 100, "next_page": next_page}}}
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: SalesloftResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy when each
    request is prepared rather than inspecting the final shared state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return salesloft_source("sl_token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format_datetime(self, value: object, expected: str) -> None:
        result = _format_datetime(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildParams:
    def test_full_refresh_endpoint_only_sets_page_size(self) -> None:
        params = _build_params(
            SALESLOFT_ENDPOINTS["groups"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params == {"per_page": 100}

    def test_incremental_endpoint_sets_ascending_sort_without_value(self) -> None:
        params = _build_params(
            SALESLOFT_ENDPOINTS["people"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updated_at",
        )
        assert params == {"per_page": 100, "sort_direction": "ASC"}

    def test_incremental_endpoint_sets_updated_at_filter(self) -> None:
        params = _build_params(
            SALESLOFT_ENDPOINTS["people"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert params["sort_direction"] == "ASC"
        assert params["updated_at[gte]"] == "2026-03-04T02:58:14.000Z"

    def test_incremental_field_value_ignored_when_flag_off(self) -> None:
        params = _build_params(
            SALESLOFT_ENDPOINTS["people"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert "updated_at[gte]" not in params

    def test_falls_back_to_updated_at_when_field_missing(self) -> None:
        params = _build_params(
            SALESLOFT_ENDPOINTS["accounts"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field=None,
        )
        assert "updated_at[gte]" in params


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(SALESLOFT_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session_factory, status_code, expected) -> None:
        mock_session_factory.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        assert validate_credentials("sl_token") is expected

        call = mock_session_factory.return_value.get.call_args
        assert call.args[0] == f"{SALESLOFT_BASE_URL}/me"
        assert call.kwargs["headers"]["Authorization"] == "Bearer sl_token"

    @mock.patch(SALESLOFT_SESSION_PATCH)
    def test_validate_credentials_swallows_transport_errors(self, mock_session_factory) -> None:
        mock_session_factory.return_value.get.side_effect = requests.ConnectionError("boom")

        assert validate_credentials("sl_token") is False


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_next_page_is_null(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session, [_response([{"id": 1}, {"id": 2}], next_page=2), _response([{"id": 3}], next_page=None)]
        )

        rows = _rows(_source("people", _make_manager()))

        assert [row["id"] for row in rows] == [1, 2, 3]
        assert session.send.call_count == 2
        # First request carries the static params; the next page rides the `page` cursor.
        assert params[0]["per_page"] == 100
        assert "page" not in params[0]
        assert params[1]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_after_yielding_each_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], next_page=2), _response([{"id": 2}], next_page=None)])
        manager = _make_manager()

        _rows(_source("people", manager))

        # State saved once: after page 1, pointing at page 2. No save after the final page.
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert saved == SalesloftResumeConfig(next_page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 9}], next_page=None)])

        rows = _rows(_source("people", _make_manager(SalesloftResumeConfig(next_page=5))))

        assert [row["id"] for row in rows] == [9]
        assert params[0]["page"] == 5

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_legacy_next_url_state(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 9}], next_page=None)])
        legacy = SalesloftResumeConfig(next_url=f"{SALESLOFT_BASE_URL}/people?per_page=100&page=7")

        _rows(_source("people", _make_manager(legacy)))

        assert params[0]["page"] == 7

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], next_page=None)])

        assert _rows(_source("people", _make_manager())) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_sent_on_first_request(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}], next_page=None)])

        _rows(
            _source(
                "people",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        assert params[0]["sort_direction"] == "ASC"
        assert params[0]["updated_at[gte]"] == "2026-03-04T02:58:14.000Z"

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_on_retryable_status_then_succeeds(self, MockSession, _mock_sleep) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(None, next_page=None, status=429),
                _response(None, next_page=None, status=503),
                _response([{"id": 1}], next_page=None),
            ],
        )

        rows = _rows(_source("people", _make_manager()))

        assert [row["id"] for row in rows] == [1]
        assert session.send.call_count == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_retryable_status_raises(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, next_page=None, status=404)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("people", _make_manager()))


class TestSalesloftSource:
    @pytest.mark.parametrize("endpoint", sorted(SALESLOFT_ENDPOINTS.keys()))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, MockSession, endpoint: str) -> None:
        MockSession.return_value.headers = {}
        response = _source(endpoint, _make_manager())

        config = SALESLOFT_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"

        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_partition_key_is_always_created_at_never_updated_at(self) -> None:
        for config in SALESLOFT_ENDPOINTS.values():
            assert config.partition_key in (None, "created_at")
