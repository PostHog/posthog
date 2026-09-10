import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
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
    @freeze_time("2026-06-15T12:00:00Z")
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

    def test_full_page_advances_to_next_page(self) -> None:
        paginator = self._paginator()
        paginator.update_state(_response({"articles": []}), [{"a": 1}, {"a": 2}])
        assert paginator.has_next_page is True
        request = mock.MagicMock()
        request.params = {}
        paginator.update_request(request)
        assert request.params == {"page": 1}

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

    def test_no_cap_log_below_cap(self) -> None:
        logger = mock.MagicMock()
        paginator = self._paginator(logger)
        paginator.update_state(_response({"articles": []}), [{"a": 1}, {"a": 2}])
        assert paginator.has_next_page is True
        logger.warning.assert_not_called()


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

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_without_watermark_sorts_but_does_not_filter(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"articles": []})])

        _rows(_source("articles", _make_manager(), should_use_incremental_field=True))

        params = snapshots[0][1]
        assert "from" not in params
        # The cursor-field sort must apply from the first incremental sync so sort_mode holds.
        assert params["sortBy"] == "reverseDate"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_uses_stable_sort_and_no_filter(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"articles": []})])

        _rows(_source("articles", _make_manager(), should_use_incremental_field=False))

        params = snapshots[0][1]
        assert "from" not in params
        assert params["sortBy"] == "reverseAddDate"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_reference_endpoint_passes_no_sort(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"results": []})])

        _rows(_source("journalists", _make_manager()))

        assert "sortBy" not in snapshots[0][1]


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_starts_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"articles": []})])

        _rows(_source("articles", _make_manager(PerigonResumeConfig(page=7))))

        assert snapshots[0][1]["page"] == 7

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_state_saved_after_each_full_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"articleId": str(i)} for i in range(100)]
        _wire(session, [_response({"articles": full_page}), _response({"articles": []})])
        manager = _make_manager()

        _rows(_source("articles", manager))

        assert manager.save_state.called
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, PerigonResumeConfig)
        assert saved.page == 1


class TestPerigonSourceResponse:
    @parameterized.expand([(name,) for name in PERIGON_ENDPOINTS])
    def test_primary_keys_and_sort_mode_match_config(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        config = PERIGON_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode

    def test_articles_partitioned_on_stable_pub_date(self) -> None:
        response = _source("articles", _make_manager())
        assert response.partition_keys == ["pubDate"]
        assert response.partition_mode == "datetime"

    def test_stories_partitioned_on_created_at_not_updated_at(self) -> None:
        # updatedAt changes on every new article in the cluster — partitioning on it would
        # rewrite partitions each sync.
        response = _source("stories", _make_manager())
        assert response.partition_keys == ["createdAt"]

    def test_full_refresh_endpoint_has_no_partition(self) -> None:
        response = _source("topics", _make_manager())
        assert response.partition_keys is None
        assert response.partition_mode is None


class TestValidateCredentials:
    @pytest.mark.parametrize("status,expected", [(200, True), (401, False), (403, False)])
    def test_status_maps_to_validity(self, status: int, expected: bool) -> None:
        with mock.patch(PERIGON_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
            ok, returned_status = validate_credentials("key")
            assert ok is expected
            assert returned_status == status

    def test_network_error_is_invalid(self) -> None:
        with mock.patch(PERIGON_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("key") == (False, None)

    def test_schema_probe_hits_that_endpoint(self) -> None:
        with mock.patch(PERIGON_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
            validate_credentials("key", path=PERIGON_ENDPOINTS["stories"].path)
            url = mock_session.return_value.get.call_args.args[0]
            assert url.startswith(f"{PERIGON_BASE_URL}/v1/stories/all")
