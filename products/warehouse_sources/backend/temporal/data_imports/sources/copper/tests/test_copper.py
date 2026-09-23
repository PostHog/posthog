import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.copper.copper import (
    COPPER_BASE_URL,
    COPPER_DEFAULT_PAGE_SIZE,
    CopperResumeConfig,
    _iter_related_items,
    _to_unix_seconds,
    copper_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.copper.settings import (
    COPPER_ENDPOINTS,
    RELATED_ITEM_PARENTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the copper module.
COPPER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.copper.copper.make_tracked_session"
)


def _response(items: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(items).encode() if items is not None else b""
    return resp


def _records(ids: list[int]) -> list[dict[str, Any]]:
    return [{"id": i, "date_created": 1700000000 + i, "date_modified": 1700000100 + i} for i in ids]


def _make_manager(resume_state: CopperResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's JSON body AT SEND TIME.

    The paginator injects `page_number` into a single body dict that's mutated in place across pages,
    so inspecting it after the run shows only the final state — snapshot a copy at prepare time.
    """
    session.headers = {}
    body_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        body_snapshots.append(dict(request.json) if request.json else {})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return body_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return copper_source(
        api_key="key",
        user_email="user@example.com",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestToUnixSeconds:
    @parameterized.expand(
        [
            ("none", None, None),
            ("int", 1700000000, 1700000000),
            ("float", 1700000000.7, 1700000000),
            ("numeric_string", "1700000000", 1700000000),
            ("bool_true", True, None),
            ("garbage", "not-a-number", None),
        ]
    )
    def test_scalar_coercion(self, _name: str, value: Any, expected: int | None) -> None:
        assert _to_unix_seconds(value) == expected

    def test_datetime_coercion(self) -> None:
        dt = datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        assert _to_unix_seconds(dt) == int(dt.timestamp())

    def test_naive_datetime_treated_as_utc(self) -> None:
        naive = datetime(2023, 11, 14, 22, 13, 20)
        assert _to_unix_seconds(naive) == int(datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC).timestamp())

    def test_date_treated_as_utc(self) -> None:
        assert _to_unix_seconds(date(2023, 11, 14)) == int(datetime(2023, 11, 14, tzinfo=UTC).timestamp())


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_terminates_on_short_first_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(_records([1, 2]))])
        manager = _make_manager()

        rows = _rows(_source("people", manager))

        assert [r["id"] for r in rows] == [1, 2]
        # A short first page stops the loop with no extra empty-page request and no checkpoint.
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])
        manager = _make_manager()

        rows = _rows(_source("companies", manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_next_page_after_each_full_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_a = _records(list(range(COPPER_DEFAULT_PAGE_SIZE)))
        full_b = _records(list(range(COPPER_DEFAULT_PAGE_SIZE, 2 * COPPER_DEFAULT_PAGE_SIZE)))
        tail = _records([99999])
        bodies = _wire(session, [_response(full_a), _response(full_b), _response(tail)])
        manager = _make_manager()

        rows = _rows(_source("people", manager))

        assert len(rows) == 2 * COPPER_DEFAULT_PAGE_SIZE + 1
        # Requests walk pages 1, 2, 3; a checkpoint pointing at the next page is saved after each
        # full page, and the short final page ends the loop without a checkpoint.
        assert [b["page_number"] for b in bodies] == [1, 2, 3]
        saved_pages = [call.args[0].page_number for call in manager.save_state.call_args_list]
        assert saved_pages == [2, 3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_starts_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response(_records([1]))])
        manager = _make_manager(CopperResumeConfig(page_number=4))

        _rows(_source("people", manager))

        assert bodies[0]["page_number"] == 4
        manager.load_state.assert_called_once()


class TestSearchBody:
    @parameterized.expand(
        [
            ("people", "date_modified", "minimum_modified_date"),
            ("people", "date_created", "minimum_created_date"),
            ("activities", "activity_date", "minimum_activity_date"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_sets_endpoint_filter_param(
        self, endpoint: str, incremental_field: str, min_param: str, MockSession
    ) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response([])])
        manager = _make_manager()

        _rows(
            _source(
                endpoint,
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
                incremental_field=incremental_field,
            )
        )

        body = bodies[0]
        assert body[min_param] == 1700000000
        assert body["page_size"] == COPPER_DEFAULT_PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_sorts_on_the_chosen_field(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response([])])

        _rows(
            _source(
                "people",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
                incremental_field="date_modified",
            )
        )

        assert bodies[0]["sort_by"] == "date_modified"
        assert bodies[0]["sort_direction"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_activities_search_sends_no_sort_params(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response([])])

        _rows(
            _source(
                "activities",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
                incremental_field="activity_date",
            )
        )

        # `/activities/search` documents no sort params, so sending one risks a rejected request.
        assert "sort_by" not in bodies[0]
        assert "sort_direction" not in bodies[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_activities_full_refresh_omits_the_watermark(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response([])])

        _rows(_source("activities", _make_manager(), should_use_incremental_field=False))

        assert "minimum_activity_date" not in bodies[0]
        assert bodies[0]["page_size"] == COPPER_DEFAULT_PAGE_SIZE

    @parameterized.expand([("incremental", True), ("full_refresh", False)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_activities_cap_the_window_at_the_sync_start(
        self, _name: str, should_use_incremental_field: bool, MockSession
    ) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response([])])

        before = int(datetime.now(UTC).timestamp())
        _rows(
            _source(
                "activities",
                _make_manager(),
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=1700000000,
                incremental_field="activity_date",
            )
        )
        after = int(datetime.now(UTC).timestamp())

        # `activity_date` is customer-editable, so a row dated far ahead would otherwise become the
        # watermark and hide every later activity behind it.
        assert before <= bodies[0]["maximum_activity_date"] <= after

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_sorts_by_created_for_searchable(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response([])])
        manager = _make_manager()

        _rows(_source("people", manager, should_use_incremental_field=False))

        body = bodies[0]
        assert body["sort_by"] == "date_created"
        assert "minimum_modified_date" not in body
        assert "minimum_created_date" not in body


class TestReferenceEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_get_no_body_and_no_resume(self, MockSession) -> None:
        session = MockSession.return_value
        bodies = _wire(session, [_response([{"id": 1, "name": "Won"}])])
        manager = _make_manager()

        rows = _rows(_source("loss_reasons", manager))

        assert rows == [{"id": 1, "name": "Won"}]
        assert session.send.call_count == 1
        # GET reference endpoints carry no request body and never consult the resumable manager.
        assert bodies[0] == {}
        manager.can_resume.assert_not_called()


class TestActivityTypes:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flattens_the_category_envelope(self, MockSession) -> None:
        session = MockSession.return_value
        envelope = {
            "user": [{"id": 0, "category": "user", "name": "Note"}],
            "system": [{"id": 1, "category": "system", "name": "Property Changed"}],
        }
        _wire(session, [_response(envelope)])

        response = _source("activity_types", _make_manager())
        rows = _rows(response)

        assert rows == [envelope["user"][0], envelope["system"][0]]
        # Ids repeat across the two categories, so the category has to be part of the key.
        assert response.primary_keys == ["id", "category"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_envelope_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"user": [], "system": []})])

        assert _rows(_source("activity_types", _make_manager())) == []


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch("tenacity.nap.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_retries_then_succeeds(self, _name: str, status_code: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, status_code=status_code), _response(_records([1]))])
        manager = _make_manager()

        rows = _rows(_source("people", manager))

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 2


class TestRedaction:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_registers_api_key_for_redaction(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(_records([1]))])

        _rows(_source("people", _make_manager()))

        assert MockSession.call_args.kwargs["redact_values"] == ("key",)


class TestSourceResponseMetadata:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_metadata_for_searchable(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(_records([1]))])

        response = _source("opportunities", _make_manager())
        rows = _rows(response)

        assert response.name == "opportunities"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date_created"]
        assert response.sort_mode == "asc"
        assert [r["id"] for r in rows] == [1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_activities_declare_descending_arrival_order(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(_records([1]))])

        response = _source("activities", _make_manager())

        # `/activities/search` answers newest-first and takes no sort param to change that.
        assert response.sort_mode == "desc"
        assert response.partition_keys == ["date_created"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_metadata_for_reference(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}])])

        response = _source("pipelines", _make_manager())

        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    @mock.patch(COPPER_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        valid, error = validate_credentials("key", "user@example.com")

        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    @mock.patch(COPPER_SESSION_PATCH)
    def test_transport_error_maps_to_invalid(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")

        valid, error = validate_credentials("key", "user@example.com")

        assert valid is False
        assert error is not None

    @mock.patch(COPPER_SESSION_PATCH)
    def test_registers_api_key_for_redaction(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("secret-key", "user@example.com")

        assert mock_session.call_args.kwargs["redact_values"] == ("secret-key",)


def _fake_api(
    get_routes: dict[str, Any] | None = None,
    search_pages: dict[str, list[list[dict[str, Any]]]] | None = None,
) -> mock.MagicMock:
    """A session answering Copper paths from a routing table; anything unrouted is a 404."""
    routes = get_routes or {}
    pages = search_pages or {}

    def _get(url: str, params: Any = None, timeout: Any = None) -> Response:
        path = url.removeprefix(COPPER_BASE_URL)
        if path not in routes:
            return _response(None, status_code=404)
        return _response(routes[path])

    def _post(url: str, json: Any = None, timeout: Any = None) -> Response:
        path = url.removeprefix(COPPER_BASE_URL)
        endpoint_pages = pages.get(path, [])
        index = json["page_number"] - 1
        return _response(endpoint_pages[index] if index < len(endpoint_pages) else [])

    session = mock.MagicMock()
    session.get.side_effect = _get
    session.post.side_effect = _post
    return session


def _requested_paths(session: mock.MagicMock) -> list[str]:
    return [call.args[0].removeprefix(COPPER_BASE_URL) for call in session.get.call_args_list]


class TestFieldLayouts:
    @mock.patch(COPPER_SESSION_PATCH)
    def test_fans_out_per_entity_and_per_opportunity_pipeline(self, mock_session) -> None:
        layout = [{"field_id": 0, "field_key": "full_name", "field_type": "static_field"}]
        session = _fake_api(
            {
                "/pipelines": [{"id": 5}, {"id": 6}],
                "/field_layouts/by_entity/people": layout,
                "/field_layouts/by_entity/opportunities": layout,
            }
        )
        mock_session.return_value = session

        rows = _rows(_source("field_layouts", _make_manager()))

        # Each row is stamped with the layout it came from — the response itself carries neither.
        assert rows == [
            {
                "entity_type": "people",
                "pipeline_id": 0,
                "field_id": 0,
                "field_key": "full_name",
                "field_type": "static_field",
            },
            {
                "entity_type": "opportunities",
                "pipeline_id": 5,
                "field_id": 0,
                "field_key": "full_name",
                "field_type": "static_field",
            },
            {
                "entity_type": "opportunities",
                "pipeline_id": 6,
                "field_id": 0,
                "field_key": "full_name",
                "field_type": "static_field",
            },
        ]

    @mock.patch(COPPER_SESSION_PATCH)
    def test_only_opportunities_carry_a_pipeline_param(self, mock_session) -> None:
        layout = [{"field_id": 0}]
        session = _fake_api(
            {
                "/pipelines": [{"id": 5}],
                "/field_layouts/by_entity/people": layout,
                "/field_layouts/by_entity/opportunities": layout,
            }
        )
        mock_session.return_value = session

        _rows(_source("field_layouts", _make_manager()))

        params_by_path = {
            call.args[0].removeprefix(COPPER_BASE_URL): call.kwargs["params"] for call in session.get.call_args_list
        }
        # Copper rejects an opportunities layout request without a pipeline, and rejects the param
        # on every other entity.
        assert params_by_path["/field_layouts/by_entity/opportunities"] == {"pipeline_id": 5}
        assert params_by_path["/field_layouts/by_entity/people"] is None

    @mock.patch(COPPER_SESSION_PATCH)
    def test_entity_copper_does_not_serve_is_skipped(self, mock_session) -> None:
        session = _fake_api({"/pipelines": [], "/field_layouts/by_entity/tasks": [{"field_id": 3}]})
        mock_session.return_value = session

        rows = _rows(_source("field_layouts", _make_manager()))

        # The other five entities 404 on this account; the walk keeps going instead of failing.
        assert rows == [{"entity_type": "tasks", "pipeline_id": 0, "field_id": 3}]


class TestRelatedItems:
    @mock.patch(COPPER_SESSION_PATCH)
    def test_stamps_each_edge_with_the_record_it_was_read_from(self, mock_session) -> None:
        session = _fake_api(
            {"/people/7/related": [{"id": 208105, "type": "project"}, {"id": 44, "type": "company"}]},
            {"/people/search": [[{"id": 7}]]},
        )
        mock_session.return_value = session

        rows = _rows(_source("related_items", _make_manager()))

        assert rows == [
            {"parent_type": "person", "parent_id": 7, "id": 208105, "type": "project"},
            {"parent_type": "person", "parent_id": 7, "id": 44, "type": "company"},
        ]

    @mock.patch(COPPER_SESSION_PATCH)
    def test_walks_every_relatable_entity_type(self, mock_session) -> None:
        session = _fake_api({}, {config.path: [[]] for config in COPPER_ENDPOINTS.values()})
        mock_session.return_value = session

        _rows(_source("related_items", _make_manager()))

        searched = [call.args[0].removeprefix(COPPER_BASE_URL) for call in session.post.call_args_list]
        assert searched == [
            "/leads/search",
            "/people/search",
            "/companies/search",
            "/opportunities/search",
            "/projects/search",
            "/tasks/search",
        ]

    @mock.patch(COPPER_SESSION_PATCH)
    def test_record_deleted_mid_walk_is_skipped(self, mock_session) -> None:
        session = _fake_api(
            {"/people/8/related": [{"id": 1, "type": "company"}]},
            {"/people/search": [[{"id": 7}, {"id": 8}]]},
        )
        mock_session.return_value = session

        rows = _rows(_source("related_items", _make_manager()))

        # Person 7 was deleted between the search page and its related lookup, so it 404s.
        assert "/people/7/related" in _requested_paths(session)
        assert rows == [{"parent_type": "person", "parent_id": 8, "id": 1, "type": "company"}]

    def test_checkpoints_the_next_position_after_each_page(self) -> None:
        session = _fake_api(
            {"/leads/1/related": [{"id": 1, "type": "task"}], "/leads/2/related": []},
            {"/leads/search": [[{"id": 1}], [{"id": 2}]]},
        )
        manager = _make_manager()

        list(_iter_related_items(session, COPPER_ENDPOINTS["related_items"].path, manager, page_size=1))

        checkpoints = [(c.args[0].parent_index, c.args[0].page_number) for c in manager.save_state.call_args_list]
        # Leads pages 1 and 2, then the walk moves on to people (index 1) at page 1. Every later
        # parent contributes one more checkpoint as its single empty page ends it.
        assert checkpoints[:3] == [(0, 2), (0, 3), (1, 1)]

    def test_final_parent_leaves_no_checkpoint_behind(self) -> None:
        session = _fake_api({}, {})
        manager = _make_manager()

        list(_iter_related_items(session, COPPER_ENDPOINTS["related_items"].path, manager, page_size=1))

        saved = [c.args[0].parent_index for c in manager.save_state.call_args_list]
        # A checkpoint past the last parent would make a retry resume onto nothing.
        assert max(saved) == len(RELATED_ITEM_PARENTS) - 1
        manager.clear_state.assert_called_once()

    def test_malformed_search_page_fails_loudly(self) -> None:
        null_page = Response()
        null_page.status_code = 200
        null_page._content = b"null"
        session = _fake_api({}, {})
        session.post.side_effect = lambda url, json=None, timeout=None: null_page
        manager = _make_manager()

        with pytest.raises(ValueError):
            list(_iter_related_items(session, COPPER_ENDPOINTS["related_items"].path, manager, page_size=1))

    def test_resumes_from_the_saved_parent_and_page(self) -> None:
        session = _fake_api(
            {"/projects/9/related": [{"id": 3, "type": "task"}]},
            {"/projects/search": [[], [], [{"id": 9}]]},
        )
        manager = _make_manager(CopperResumeConfig(page_number=3, parent_index=4))

        rows = [
            row for page in _iter_related_items(session, "/{entity}/{record_id}/related", manager, 1) for row in page
        ]

        searched = [call.args[0].removeprefix(COPPER_BASE_URL) for call in session.post.call_args_list]
        # Projects is index 4, so leads through opportunities are not re-walked, and projects
        # restarts at page 3 rather than page 1.
        assert searched == ["/projects/search", "/projects/search", "/tasks/search"]
        assert session.post.call_args_list[0].kwargs["json"]["page_number"] == 3
        assert rows == [{"parent_type": "project", "parent_id": 9, "id": 3, "type": "task"}]
