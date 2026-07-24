import json
from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.convertkit import (
    ConvertKitResumeConfig,
    _format_incremental_value,
    convertkit_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the convertkit module.
CONVERTKIT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.convertkit.make_tracked_session"
)


def _page(key: str, ids: list[int], *, has_next: bool, end_cursor: str | None) -> Response:
    body: dict[str, Any] = {
        key: [{"id": i} for i in ids],
        "pagination": {"has_next_page": has_next, "end_cursor": end_cursor},
    }
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: ConvertKitResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return convertkit_source(
        api_key="key", endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
    )


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "cursor-value", "cursor-value"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        result = _format_incremental_value(value)
        assert result == expected
        assert "+00:00" not in result


class TestRequestParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_includes_per_page_and_status_all(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("subscribers", [1], has_next=False, end_cursor=None)])

        _rows(_source("subscribers", _make_manager()))

        assert params[0]["per_page"] == 1000
        # subscribers must request every status, not just active.
        assert params[0]["status"] == "all"

    @parameterized.expand(
        [
            ("created_at", "created_after", "updated_after"),
            ("updated_at", "updated_after", "created_after"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_field_maps_to_filter_param(
        self, incremental_field: str, expected_param: str, other_param: str, MockSession
    ) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("subscribers", [1], has_next=False, end_cursor=None)])

        _rows(
            _source(
                "subscribers",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                incremental_field=incremental_field,
            )
        )

        assert params[0][expected_param] == "2026-01-02T03:04:05Z"
        # Only the chosen field's param is set.
        assert other_param not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_when_not_using_incremental(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("subscribers", [1], has_next=False, end_cursor=None)])

        _rows(
            _source(
                "subscribers",
                _make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
                incremental_field="created_at",
            )
        )

        assert "created_after" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_on_first_sync_without_last_value(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("subscribers", [1], has_next=False, end_cursor=None)])

        _rows(
            _source(
                "subscribers",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
                incremental_field="created_at",
            )
        )

        assert "created_after" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_for_non_incremental_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("broadcasts", [1], has_next=False, end_cursor=None)])

        # broadcasts has no server-side timestamp filter and no status param.
        _rows(
            _source(
                "broadcasts",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
                incremental_field="created_at",
            )
        )

        assert "created_after" not in params[0]
        assert "status" not in params[0]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_no_next_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page("subscribers", [1, 2], has_next=True, end_cursor="C2"),
                _page("subscribers", [3], has_next=False, end_cursor=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("subscribers", manager))

        assert [r["id"] for r in rows] == [1, 2, 3]
        assert session.send.call_count == 2
        # The second request carries the cursor from the first page.
        assert params[1]["after"] == "C2"
        # State saved once, pointing at the first page's end_cursor; the last page ends without a save.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ConvertKitResumeConfig(after="C2")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("subscribers", [9], has_next=False, end_cursor=None)])

        manager = _make_manager(ConvertKitResumeConfig(after="C5"))
        rows = _rows(_source("subscribers", manager))

        assert [r["id"] for r in rows] == [9]
        manager.load_state.assert_called_once()
        assert params[0]["after"] == "C5"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_end_cursor_missing_despite_has_next(self, MockSession) -> None:
        session = MockSession.return_value
        # has_next_page true but no end_cursor to advance to — must stop, not loop.
        _wire(session, [_page("subscribers", [1], has_next=True, end_cursor=None)])

        manager = _make_manager()
        rows = _rows(_source("subscribers", manager))

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_no_rows_and_does_not_save(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("subscribers", [], has_next=False, end_cursor=None)])

        manager = _make_manager()
        rows = _rows(_source("subscribers", manager))

        assert rows == []
        manager.save_state.assert_not_called()


class TestValidateCredentials:
    def _response(self, status_code: int) -> mock.MagicMock:
        response = mock.MagicMock()
        response.status_code = status_code
        return response

    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_source_create", 403, None, True),
            ("forbidden_for_specific_endpoint", 403, "subscribers", False),
            ("server_error", 500, None, False),
        ]
    )
    @mock.patch(CONVERTKIT_SESSION_PATCH)
    def test_status_code_mapping(
        self, _name: str, status: int, endpoint: str | None, expected_valid: bool, mock_session
    ) -> None:
        mock_session.return_value.get.return_value = self._response(status)
        is_valid, _error = validate_credentials("key", endpoint)
        assert is_valid is expected_valid

    @mock.patch(CONVERTKIT_SESSION_PATCH)
    def test_network_error_is_invalid(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        is_valid, error = validate_credentials("key")
        assert is_valid is False
        assert error is not None

    @mock.patch(CONVERTKIT_SESSION_PATCH)
    def test_unknown_endpoint_returns_error_without_request(self, mock_session) -> None:
        is_valid, error = validate_credentials("key", "not_a_real_endpoint")
        assert is_valid is False
        assert error is not None
        mock_session.assert_not_called()


class TestConvertKitSource:
    @parameterized.expand(
        [
            ("subscribers", ["id"], "created_at"),
            ("purchases", ["id"], "transaction_time"),
            ("custom_fields", ["id"], None),
            ("email_templates", ["id"], None),
        ]
    )
    def test_source_response_partitioning(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_threads_manager_and_yields(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("tags", [7], has_next=False, end_cursor=None)])

        manager = _make_manager()
        rows = _rows(_source("tags", manager))

        assert [r["id"] for r in rows] == [7]
        manager.can_resume.assert_called_once()
