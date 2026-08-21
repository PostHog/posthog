import json
from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.profound.profound import (
    DEFAULT_REPORT_LOOKBACK_DAYS,
    REPORT_PAGE_SIZE,
    ProfoundCategoriesError,
    ProfoundResumeConfig,
    _to_report_date,
    fetch_category_ids,
    profound_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.profound.settings import PROFOUND_ENDPOINTS

CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
PROFOUND_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.profound.profound.make_tracked_session"
)
FETCH_CATEGORIES_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.profound.profound.fetch_category_ids"
)


def _json_response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _report_response(rows: list[dict[str, Any]], *, next_cursor: str | None = None) -> Response:
    return _json_response({"info": {"next_cursor": next_cursor}, "data": rows})


def _make_manager(resume_state: ProfoundResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's JSON body at send time."""
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(json.loads(json.dumps(request.json)) if request.json is not None else {})
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return profound_source(
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestFetchCategoryIds:
    @mock.patch(PROFOUND_SESSION_PATCH)
    def test_ids_are_read_from_a_bare_array(self, MockSession) -> None:
        MockSession.return_value.get.return_value = _json_response([{"id": "c1"}, {"id": "c2"}])

        assert fetch_category_ids("key") == ["c1", "c2"]

    @mock.patch(PROFOUND_SESSION_PATCH)
    def test_rows_without_an_id_are_skipped(self, MockSession) -> None:
        MockSession.return_value.get.return_value = _json_response([{"id": "c1"}, {"name": "no id"}])

        assert fetch_category_ids("key") == ["c1"]

    @mock.patch(PROFOUND_SESSION_PATCH)
    def test_an_unexpected_shape_raises(self, MockSession) -> None:
        # Silently syncing 0 report rows would look like an empty account.
        MockSession.return_value.get.return_value = _json_response({"data": []})

        try:
            fetch_category_ids("key")
        except ProfoundCategoriesError:
            return
        raise AssertionError("expected ProfoundCategoriesError")

    @mock.patch(PROFOUND_SESSION_PATCH)
    def test_the_request_never_follows_a_redirect(self, MockSession) -> None:
        # The API key rides the custom X-API-Key header, which requests would replay to a redirect.
        session = MockSession.return_value
        session.get.return_value = _json_response([])

        fetch_category_ids("key")

        assert session.get.call_args.kwargs["allow_redirects"] is False


class TestReportRequests:
    @parameterized.expand(
        [
            ("datetime", datetime(2026, 6, 9, 15, 0, tzinfo=UTC), "2026-06-09"),
            ("date", date(2026, 6, 9), "2026-06-09"),
            ("iso_string", "2026-06-09T15:00:00Z", "2026-06-09"),
            ("none", None, None),
            ("garbage", "not-a-date", None),
        ]
    )
    def test_to_report_date(self, _name: str, value: Any, expected: str | None) -> None:
        # The report body takes YYYY-MM-DD; a full timestamp is rejected with a 422.
        assert _to_report_date(value) == expected

    @mock.patch(FETCH_CATEGORIES_PATCH, return_value=["c1"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_report_body_names_the_category_and_window(self, MockSession, _mock_categories) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_report_response([{"date": "2026-06-09"}])])

        _rows(
            _source(
                "Visibility",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 6, 1),
                today=date(2026, 6, 15),
            )
        )

        body = bodies[0]
        assert body["category_id"] == "c1"
        assert body["start_date"] == "2026-06-01"
        assert body["end_date"] == "2026-06-15"
        assert body["group_by"] == ["date"]
        assert body["metrics"] == PROFOUND_ENDPOINTS["Visibility"].metrics
        assert body["limit"] == REPORT_PAGE_SIZE

    @mock.patch(FETCH_CATEGORIES_PATCH, return_value=["c1"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_a_first_sync_uses_the_default_lookback(self, MockSession, _mock_categories) -> None:
        # start_date is required, so a sync with no watermark still needs a bounded window.
        session = MockSession.return_value
        bodies = _wire(session, [_report_response([])])

        _rows(_source("Citations", _make_manager(), today=date(2026, 6, 15)))

        assert bodies[0]["start_date"] == "2025-06-15"
        assert DEFAULT_REPORT_LOOKBACK_DAYS == 365

    @mock.patch(FETCH_CATEGORIES_PATCH, return_value=["c1"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_ignores_the_stored_watermark(self, MockSession, _mock_categories) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_report_response([])])

        _rows(
            _source(
                "Citations",
                _make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=date(2026, 6, 1),
                today=date(2026, 6, 15),
            )
        )

        assert bodies[0]["start_date"] == "2025-06-15"

    @mock.patch(FETCH_CATEGORIES_PATCH, return_value=["c1"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_the_body_cursor_pages_within_one_category(self, MockSession, _mock_categories) -> None:
        session = MockSession.return_value
        bodies = _wire(
            session,
            [
                _report_response([{"domain": "a.com"}], next_cursor="cur1"),
                _report_response([{"domain": "b.com"}]),
            ],
        )

        rows = _rows(_source("Citations", _make_manager(), today=date(2026, 6, 15)))

        assert [row["domain"] for row in rows] == ["a.com", "b.com"]
        assert "cursor" not in bodies[0]
        assert bodies[1]["cursor"] == "cur1"


class TestReportFanOut:
    @mock.patch(FETCH_CATEGORIES_PATCH, return_value=["c1", "c2"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_every_category_is_requested_and_stamped_onto_its_rows(self, MockSession, _mock_categories) -> None:
        # The response echoes only the grouped fields, so without the stamp the rows from two
        # categories would be indistinguishable and would collide on the primary key.
        session = MockSession.return_value
        bodies = _wire(session, [_report_response([{"domain": "a.com"}]), _report_response([{"domain": "a.com"}])])

        rows = _rows(_source("Citations", _make_manager(), today=date(2026, 6, 15)))

        assert [b["category_id"] for b in bodies] == ["c1", "c2"]
        assert [row["category_id"] for row in rows] == ["c1", "c2"]

    @mock.patch(FETCH_CATEGORIES_PATCH, return_value=["c1", "c2", "c3"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_the_categories_already_finished(self, MockSession, _mock_categories) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_report_response([{"domain": "b.com"}]), _report_response([{"domain": "c.com"}])])

        _rows(
            _source(
                "Citations",
                _make_manager(ProfoundResumeConfig(category_id="c2")),
                today=date(2026, 6, 15),
            )
        )

        assert [b["category_id"] for b in bodies] == ["c2", "c3"]

    @mock.patch(FETCH_CATEGORIES_PATCH, return_value=["c1", "c2"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_the_saved_cursor_only_for_its_own_category(self, MockSession, _mock_categories) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_report_response([{"domain": "a.com"}]), _report_response([{"domain": "b.com"}])])

        _rows(
            _source(
                "Citations",
                _make_manager(ProfoundResumeConfig(category_id="c1", cursor="mid")),
                today=date(2026, 6, 15),
            )
        )

        assert bodies[0]["cursor"] == "mid"
        # The next category starts from its first page, not from the previous category's cursor.
        assert "cursor" not in bodies[1]

    @mock.patch(FETCH_CATEGORIES_PATCH, return_value=["c1", "c2"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_a_finished_category_clears_its_cursor(self, MockSession, _mock_categories) -> None:
        # Leaving the last cursor in place would restart a finished category mid-walk on the next
        # attempt and skip its earlier pages.
        session = MockSession.return_value
        _wire(session, [_report_response([{"domain": "a.com"}], next_cursor="cur1"), _report_response([])] * 2)
        manager = _make_manager()

        _rows(_source("Citations", manager, today=date(2026, 6, 15)))

        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert ProfoundResumeConfig(category_id="c1", cursor=None) in saved

    @mock.patch(FETCH_CATEGORIES_PATCH, return_value=["c1"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_visibility_flattens_the_nested_asset(self, MockSession, _mock_categories) -> None:
        # `asset` arrives as a nested object, and a dict cannot serve as a primary key column.
        session = MockSession.return_value
        _wire(
            session,
            [_report_response([{"date": "2026-06-09", "asset": {"name": "Acme", "owned": True}}])],
        )

        rows = _rows(_source("Visibility", _make_manager(), today=date(2026, 6, 15)))

        assert rows[0]["asset_name"] == "Acme"
        assert rows[0]["asset_owned"] is True


class TestReferenceEndpoints:
    @parameterized.expand(["Categories", "Models", "Regions", "Domains"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bare_array_endpoints_need_no_wrapper_key(self, endpoint: str, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response([{"id": "1"}, {"id": "2"}])])

        rows = _rows(_source(endpoint, _make_manager()))

        assert [row["id"] for row in rows] == ["1", "2"]

    @parameterized.expand(["Assets", "Personas"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_wrapped_endpoints_select_the_data_key(self, endpoint: str, MockSession) -> None:
        # These two wrap their array in `data` where the other four return it bare.
        session = MockSession.return_value
        _wire(session, [_json_response({"data": [{"id": "1"}]})])

        rows = _rows(_source(endpoint, _make_manager()))

        assert [row["id"] for row in rows] == ["1"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reference_endpoints_send_one_request(self, MockSession) -> None:
        # They return everything at once; paginating would re-request page one forever.
        session = MockSession.return_value
        bodies = _wire(session, [_json_response([{"id": "1"}])])

        _rows(_source("Models", _make_manager()))

        assert len(bodies) == 1


class TestSourceResponseShape:
    @parameterized.expand(
        [
            ("Visibility", ["category_id", "date", "asset_name"]),
            ("Citations", ["category_id", "date", "domain"]),
            ("Categories", ["id"]),
        ]
    )
    @mock.patch(FETCH_CATEGORIES_PATCH, return_value=["c1"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_primary_keys(self, endpoint: str, expected: list[str], MockSession, _mock_categories) -> None:
        # A report row is unique only per category and day, so the key needs all three parts.
        session = MockSession.return_value
        _wire(session, [_json_response([])])

        assert _source(endpoint, _make_manager()).primary_keys == expected

    @mock.patch(FETCH_CATEGORIES_PATCH, return_value=["c1"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reports_declare_desc_so_the_watermark_lands_at_job_end(self, MockSession, _mock_categories) -> None:
        # The fan-out interleaves categories, so a per-batch watermark could skip a later
        # category's older days.
        session = MockSession.return_value
        _wire(session, [_json_response([])])

        assert _source("Visibility", _make_manager()).sort_mode == "desc"


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(PROFOUND_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected: bool, MockSession) -> None:
        resp = Response()
        resp.status_code = status
        MockSession.return_value.get.return_value = resp

        assert validate_credentials("key") is expected

    @mock.patch(PROFOUND_SESSION_PATCH)
    def test_a_transport_error_does_not_raise(self, MockSession) -> None:
        MockSession.side_effect = OSError("boom")

        assert validate_credentials("key") is False
