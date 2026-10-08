import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.perigon.perigon import (
    MAX_PAGE,
    PERIGON_BASE_URL,
    PerigonPaginator,
    PerigonResumeConfig,
    _clamp_future_value_to_now,
    _format_datetime,
    perigon_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.perigon.settings import PERIGON_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the perigon module.
PERIGON_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.perigon.perigon.make_tracked_session"
)


def _response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: PerigonResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
    """Wire a mock session; capture each request's (url, params) AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting it after the run.
    """
    session.headers = {}
    snapshots: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append((request.url, dict(request.params or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return perigon_source(
        api_key="key", endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
    )


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestClampFutureValueToNow:
    @parameterized.expand(
        [
            ("future_datetime", datetime(2027, 2, 5, tzinfo=UTC), datetime(2026, 6, 15, 12, tzinfo=UTC)),
            ("past_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)),
            ("non_iso_string_passthrough", "cursor", "cursor"),
            ("future_iso_string", "2030-01-01T00:00:00Z", datetime(2026, 6, 15, 12, tzinfo=UTC)),
        ]
    )
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_clamp(self, _name: str, value: Any, expected: Any) -> None:
        assert _clamp_future_value_to_now(value) == expected


class TestPaginator:
    def _paginator(self, logger: mock.MagicMock | None = None) -> PerigonPaginator:
        paginator = PerigonPaginator(page_size=2, endpoint="articles", logger=logger)
        request = mock.MagicMock()
        request.params = {}
        paginator.init_request(request)
        assert request.params == {"page": 0}
        return paginator

    @parameterized.expand([("short_page", [{"a": 1}]), ("empty_page", [])])
    def test_short_or_empty_page_terminates(self, _name: str, data: list[dict[str, Any]]) -> None:
        paginator = self._paginator()
        paginator.update_state(_response({"articles": []}), data)
        assert paginator.has_next_page is False

    def test_depth_cap_stops_and_logs(self) -> None:
        # Perigon rejects pagination past its 10,000-row search window; running past the cap
        # would fail every large sync mid-way.
        logger = mock.MagicMock()
        paginator = self._paginator(logger)
        paginator.page = MAX_PAGE
        paginator.update_state(_response({"articles": []}), [{"a": 1}, {"a": 2}])
        assert paginator.has_next_page is False
        logger.warning.assert_called_once()


class TestEndpointRequests:
    @parameterized.expand([(name, cfg.data_selector) for name, cfg in PERIGON_ENDPOINTS.items()])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rows_extracted_from_wrapper(self, endpoint: str, selector: str, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({selector: [{"k": "v"}]})])

        rows = _rows(_source(endpoint, _make_manager()))

        assert rows == [{"k": "v"}]
        url, params = snapshots[0]
        assert url == f"{PERIGON_BASE_URL}{PERIGON_ENDPOINTS[endpoint].path}"
        assert params["page"] == 0
        assert params["size"] == 100

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_wrapper_key_fails_loud(self, MockSession) -> None:
        session = MockSession.return_value
        # A 200 body without the expected wrapper key means the response shape changed —
        # fail loud, not 0 rows.
        _wire(session, [_response({"unexpected": []})])

        with pytest.raises(ValueError):
            _rows(_source("articles", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pagination_walks_pages_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"articleId": str(i)} for i in range(100)]
        snapshots = _wire(session, [_response({"articles": full_page}), _response({"articles": [{"articleId": "x"}]})])

        rows = _rows(_source("articles", _make_manager()))

        assert len(rows) == 101
        assert [params["page"] for _, params in snapshots] == [0, 1]


class TestIncrementalParams:
    @parameterized.expand(
        [
            ("articles", "from", "reverseDate"),
            ("stories", "updatedFrom", "updatedAt"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_watermark_passed_as_server_side_filter(self, endpoint: str, param: str, sort_by: str, MockSession) -> None:
        session = MockSession.return_value
        selector = PERIGON_ENDPOINTS[endpoint].data_selector
        snapshots = _wire(session, [_response({selector: []})])

        _rows(
            _source(
                endpoint,
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        params = snapshots[0][1]
        assert params[param] == "2026-03-04T02:58:14Z"
        assert params["sortBy"] == sort_by


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_starts_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"articles": []})])

        _rows(_source("articles", _make_manager(PerigonResumeConfig(page=7))))

        assert snapshots[0][1]["page"] == 7


class TestPerigonSourceResponse:
    @parameterized.expand([(name,) for name in PERIGON_ENDPOINTS])
    def test_primary_keys_and_sort_mode_match_config(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        config = PERIGON_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode


class TestValidateCredentials:
    def test_network_error_is_invalid(self) -> None:
        with mock.patch(PERIGON_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("key") == (False, None)
