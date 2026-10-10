import json
from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.profound.profound import (
    ProfoundCategoriesError,
    ProfoundResumeConfig,
    _to_report_date,
    fetch_category_ids,
    profound_source,
    validate_credentials,
)

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


class TestReportFanOut:
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

    @parameterized.expand([("CitationCategories", "citation-categories"), ("CitationTags", "citation-tags")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_per_category_endpoints_fan_out_and_stamp_the_category(
        self, endpoint: str, path_segment: str, MockSession
    ) -> None:
        # The rows carry only `value` and `name`, which repeat across categories, so `category_id`
        # has to come from the request for the primary key to be unique.
        session = MockSession.return_value
        _wire(
            session,
            [
                _json_response([{"id": "c1"}, {"id": "c2"}]),
                _json_response({"data": [{"value": "owned", "name": "Owned"}]}),
                _json_response({"data": [{"value": "owned", "name": "Owned"}]}),
            ],
        )

        rows = _rows(_source(endpoint, _make_manager()))

        urls = [c.args[0].url for c in session.send.call_args_list]
        assert urls[1].endswith(f"/v1/org/categories/c1/{path_segment}")
        assert urls[2].endswith(f"/v1/org/categories/c2/{path_segment}")
        assert [(row["category_id"], row["value"]) for row in rows] == [("c1", "owned"), ("c2", "owned")]
        assert all("_Categories_id" not in row for row in rows)


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


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(PROFOUND_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected: bool, MockSession) -> None:
        resp = Response()
        resp.status_code = status
        MockSession.return_value.get.return_value = resp

        assert validate_credentials("key") is expected
