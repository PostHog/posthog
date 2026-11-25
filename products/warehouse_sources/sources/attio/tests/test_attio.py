import pytest

from products.warehouse_sources.sources.attio._config import AttioSourceConfig
from products.warehouse_sources.sources.attio.attio import AttioResumeConfig, validate_credentials
from products.warehouse_sources.sources.attio.settings import ATTIO_ENDPOINTS
from products.warehouse_sources.sources.attio.source import AttioSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, route


class TestValidateCredentials:
    def test_non_ascii_key_returns_actionable_message_without_leaking_encoding_error(self):
        # A non-latin-1 key can't be encoded into the Authorization header; the raw
        # UnicodeEncodeError ("'latin-1' codec can't encode ... ordinal not in range(256)")
        # must never surface to the user.
        valid, msg = validate_credentials("bad中key")

        assert valid is False
        assert "Retype it by hand" in (msg or "")
        assert "latin-1" not in (msg or "")
        assert "ordinal not in range" not in (msg or "")


def _page(endpoint: str, start: int, count: int) -> ScriptedResponse:
    primary_key = ATTIO_ENDPOINTS[endpoint].primary_keys[0]
    rows = [
        {"id": {"workspace_id": "ws", primary_key: f"row-{i}"}, "created_at": "2024-01-01"}
        for i in range(start, start + count)
    ]
    return ScriptedResponse(json={"data": rows})


class TestAttioResume:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(AttioSource(), AttioSourceConfig(api_key="key"))

    @pytest.mark.parametrize("endpoint", ["companies", "people", "deals", "notes", "tasks"])
    def test_fresh_run_stages_next_offset_after_each_page(self, endpoint: str) -> None:
        limit = ATTIO_ENDPOINTS[endpoint].page_size
        responses = [_page(endpoint, 0, limit), _page(endpoint, limit, limit), _page(endpoint, 2 * limit, 3)]

        result = self._driver().run(endpoint, responses)
        is_post = ATTIO_ENDPOINTS[endpoint].method == "POST"

        assert result.raised is None
        assert [request.json()["offset"] if is_post else request.param("offset") for request in result.requests] == [
            offset if is_post else str(offset) for offset in (0, limit, 2 * limit)
        ]
        assert all(
            (request.json()["limit"] if is_post else request.param("limit")) == (limit if is_post else str(limit))
            for request in result.requests
        )
        assert len(result.rows) == 2 * limit + 3
        assert result.rows[-1][ATTIO_ENDPOINTS[endpoint].primary_keys[0]] == f"row-{2 * limit + 2}"
        assert result.saved_states == [
            AttioResumeConfig(offset=limit),
            AttioResumeConfig(offset=2 * limit),
        ]

    @pytest.mark.parametrize("endpoint", ["companies", "people", "lists", "notes", "tasks", "workspace_members"])
    def test_resumed_run_starts_from_saved_offset(self, endpoint: str) -> None:
        limit = ATTIO_ENDPOINTS[endpoint].page_size
        responses = [_page(endpoint, 2 * limit, limit), _page(endpoint, 3 * limit, 1)]

        result = self._driver().run(endpoint, responses, resume_state=AttioResumeConfig(offset=2 * limit))
        is_post = ATTIO_ENDPOINTS[endpoint].method == "POST"

        assert result.raised is None
        assert [request.json()["offset"] if is_post else request.param("offset") for request in result.requests] == [
            offset if is_post else str(offset) for offset in (2 * limit, 3 * limit)
        ]
        assert result.rows[0][ATTIO_ENDPOINTS[endpoint].primary_keys[0]] == f"row-{2 * limit}"
        assert result.saved_states == [AttioResumeConfig(offset=3 * limit)]

    def test_resumed_query_keeps_sort_order_in_body(self) -> None:
        # Offsets only line up across runs when every run asks for the same order.
        result = self._driver().run(
            "companies", [_page("companies", 500, 1)], resume_state=AttioResumeConfig(offset=500)
        )

        assert result.raised is None
        assert [request.json() for request in result.requests] == [
            {"sorts": [{"attribute": "created_at", "direction": "asc"}], "offset": 500, "limit": 500}
        ]


def _cursor_page(start: int, count: int, next_cursor: str | None) -> ScriptedResponse:
    rows = [
        {"id": {"workspace_id": "ws", "activity_id": f"row-{i}"}, "created_at": "2024-01-01"}
        for i in range(start, start + count)
    ]
    return ScriptedResponse(json={"data": rows, "pagination": {"next_cursor": next_cursor}})


class TestAttioCursorPagination:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(AttioSource(), AttioSourceConfig(api_key="key"))

    @pytest.mark.parametrize(
        "resume_state, responses, expected_cursors, expected_rows, expected_states",
        [
            (
                None,
                [_cursor_page(0, 2, "c1"), _cursor_page(2, 2, "c2"), _cursor_page(4, 1, None)],
                [None, "c1", "c2"],
                5,
                [AttioResumeConfig(cursor="c1"), AttioResumeConfig(cursor="c2")],
            ),
            (
                AttioResumeConfig(cursor="c2"),
                [_cursor_page(4, 2, "c3"), _cursor_page(6, 1, None)],
                ["c2", "c3"],
                3,
                [AttioResumeConfig(cursor="c3")],
            ),
        ],
    )
    def test_activities_follow_next_cursor_and_stage_it(
        self,
        resume_state: AttioResumeConfig | None,
        responses: list[ScriptedResponse],
        expected_cursors: list[str | None],
        expected_rows: int,
        expected_states: list[AttioResumeConfig],
    ) -> None:
        result = self._driver().run("activities", responses, resume_state=resume_state)

        assert result.raised is None
        assert [request.param("cursor") for request in result.requests] == expected_cursors
        assert all(request.param("limit") == "500" for request in result.requests)
        assert all(request.param("offset") is None for request in result.requests)
        assert len(result.rows) == expected_rows
        assert "activity_id" in result.rows[0]
        assert result.saved_states == expected_states


def _driver() -> SourceDriver:
    return SourceDriver(AttioSource(), AttioSourceConfig(api_key="key"))


def _parents(target: str, *ids: str) -> ScriptedResponse:
    id_field = "list_id" if target == "lists" else "object_id"
    return ScriptedResponse(json={"data": [{"id": {"workspace_id": "ws", id_field: i}} for i in ids]})


def _entries(list_id: str, start: int, count: int) -> ScriptedResponse:
    rows = [
        {"id": {"workspace_id": "ws", "list_id": list_id, "entry_id": f"e-{i}"}, "created_at": "2024-01-01"}
        for i in range(start, start + count)
    ]
    return ScriptedResponse(json={"data": rows})


def _attributes(parent_id: str, *attributes: tuple[str, str]) -> ScriptedResponse:
    rows = [
        {"id": {"workspace_id": "ws", "object_id": parent_id, "attribute_id": attribute_id}, "type": attribute_type}
        for attribute_id, attribute_type in attributes
    ]
    return ScriptedResponse(json={"data": rows})


def _values(parent_id: str, attribute_id: str, id_field: str, *value_ids: str) -> ScriptedResponse:
    rows = [
        {"id": {"workspace_id": "ws", "object_id": parent_id, "attribute_id": attribute_id, id_field: v}, "title": v}
        for v in value_ids
    ]
    return ScriptedResponse(json={"data": rows})


class TestAttioObjects:
    def test_reads_one_page_and_lifts_object_id(self) -> None:
        result = _driver().run("objects", [_parents("objects", "o1", "o2")])

        assert result.raised is None
        assert result.paths == ["/v2/objects"]
        assert result.requests[0].param("offset") is None
        assert [row["object_id"] for row in result.rows] == ["o1", "o2"]


class TestAttioListEntries:
    LIMIT = ATTIO_ENDPOINTS["list_entries"].page_size

    @pytest.mark.parametrize(
        "resume_state, entry_responses, expected_requests, expected_rows, expected_states",
        [
            (
                None,
                {
                    "/v2/lists/l1/entries/query": [_entries("l1", 0, 500), _entries("l1", 500, 2)],
                    "/v2/lists/l2/entries/query": [_entries("l2", 0, 1)],
                },
                [
                    ("/v2/lists/l1/entries/query", 0),
                    ("/v2/lists/l1/entries/query", 500),
                    ("/v2/lists/l2/entries/query", 0),
                ],
                503,
                [
                    AttioResumeConfig(fanout_key="lists/l1", offset=500),
                    AttioResumeConfig(fanout_key="lists/l1"),
                    AttioResumeConfig(fanout_key="lists/l2"),
                ],
            ),
            (
                AttioResumeConfig(fanout_key="lists/l1", offset=500),
                {
                    "/v2/lists/l1/entries/query": [_entries("l1", 500, 2)],
                    "/v2/lists/l2/entries/query": [_entries("l2", 0, 1)],
                },
                [("/v2/lists/l1/entries/query", 500), ("/v2/lists/l2/entries/query", 0)],
                3,
                [AttioResumeConfig(fanout_key="lists/l1"), AttioResumeConfig(fanout_key="lists/l2")],
            ),
            (
                AttioResumeConfig(fanout_key="lists/l1"),
                {"/v2/lists/l2/entries/query": [_entries("l2", 0, 1)]},
                [("/v2/lists/l2/entries/query", 0)],
                1,
                [AttioResumeConfig(fanout_key="lists/l2")],
            ),
        ],
        ids=["fresh", "resume_mid_list", "resume_after_list"],
    )
    def test_walks_lists_in_id_order_and_resumes_by_key(
        self,
        resume_state: AttioResumeConfig | None,
        entry_responses: dict[str, list[ScriptedResponse]],
        expected_requests: list[tuple[str, int]],
        expected_rows: int,
        expected_states: list[AttioResumeConfig],
    ) -> None:
        # The API lists l2 first; the walk sorts parents so a resume key compares across attempts.
        script = route({**entry_responses, "/v2/lists": [_parents("lists", "l2", "l1")]})

        result = _driver().run("list_entries", script, resume_state=resume_state)

        assert result.raised is None
        entry_requests = [r for r in result.requests if r.path.endswith("/entries/query")]
        assert [(r.path, r.json()["offset"]) for r in entry_requests] == expected_requests
        assert all(r.method == "POST" and r.json()["limit"] == self.LIMIT for r in entry_requests)
        assert len(result.rows) == expected_rows
        assert {"list_id", "entry_id"} <= result.rows[0].keys()
        assert "target" not in result.rows[0]
        assert result.saved_states == expected_states


class TestAttioAttributes:
    def test_reads_objects_and_lists_and_skips_a_deleted_parent(self) -> None:
        script = route(
            {
                "/v2/objects/o1/attributes": [_attributes("o1", ("a1", "text"))],
                "/v2/objects/o2/attributes": [ScriptedResponse(status=404, json={"code": "not_found"})],
                "/v2/lists/l1/attributes": [_attributes("l1", ("a2", "status"))],
                "/v2/objects": [_parents("objects", "o2", "o1")],
                "/v2/lists": [_parents("lists", "l1")],
            }
        )

        result = _driver().run("attributes", script)

        assert result.raised is None
        assert [r.path for r in result.requests if r.path.endswith("/attributes")] == [
            "/v2/lists/l1/attributes",
            "/v2/objects/o1/attributes",
            "/v2/objects/o2/attributes",
        ]
        assert all(
            r.param("show_archived") == "true" and r.param("limit") == "100"
            for r in result.requests
            if r.path.endswith("/attributes")
        )
        assert [(row["target"], row["object_id"], row["attribute_id"]) for row in result.rows] == [
            ("lists", "l1", "a2"),
            ("objects", "o1", "a1"),
        ]
        # The deleted parent yields nothing, so the last staged key is the last parent with rows.
        assert result.saved_states == [
            AttioResumeConfig(fanout_key="lists/l1"),
            AttioResumeConfig(fanout_key="objects/o1"),
        ]


class TestAttioAttributeValues:
    @pytest.mark.parametrize(
        "endpoint, attribute_type, child, id_field",
        [
            ("select_options", "select", "options", "option_id"),
            ("statuses", "status", "statuses", "status_id"),
        ],
    )
    def test_reads_values_of_matching_attributes_only(
        self, endpoint: str, attribute_type: str, child: str, id_field: str
    ) -> None:
        script = route(
            {
                f"/v2/objects/o1/attributes/b/{child}": [_values("o1", "b", id_field, "v2")],
                f"/v2/objects/o1/attributes/a/{child}": [_values("o1", "a", id_field, "v1")],
                f"/v2/lists/l1/attributes/c/{child}": [_values("l1", "c", id_field)],
                "/v2/objects/o1/attributes": [
                    _attributes("o1", ("b", attribute_type), ("x", "text"), ("a", attribute_type))
                ],
                "/v2/lists/l1/attributes": [_attributes("l1", ("c", attribute_type))],
                "/v2/objects": [_parents("objects", "o1")],
                "/v2/lists": [_parents("lists", "l1")],
            }
        )

        result = _driver().run(endpoint, script)

        assert result.raised is None
        assert [r.path for r in result.requests if r.path.endswith(child)] == [
            f"/v2/lists/l1/attributes/c/{child}",
            f"/v2/objects/o1/attributes/a/{child}",
            f"/v2/objects/o1/attributes/b/{child}",
        ]
        assert [(row["target"], row["object_id"], row["attribute_id"], row[id_field]) for row in result.rows] == [
            ("objects", "o1", "a", "v1"),
            ("objects", "o1", "b", "v2"),
        ]
        assert result.saved_states == [
            AttioResumeConfig(fanout_key="objects/o1/a"),
            AttioResumeConfig(fanout_key="objects/o1/b"),
        ]

    def test_resume_skips_attribute_listing_of_finished_parents(self) -> None:
        script = route(
            {
                "/v2/objects/o1/attributes/b/options": [_values("o1", "b", "option_id", "v2")],
                "/v2/objects/o1/attributes": [_attributes("o1", ("a", "select"), ("b", "select"))],
                "/v2/objects": [_parents("objects", "o1")],
                "/v2/lists": [_parents("lists", "l1")],
            }
        )

        result = _driver().run("select_options", script, resume_state=AttioResumeConfig(fanout_key="objects/o1/a"))

        assert result.raised is None
        assert result.paths == [
            "/v2/lists",
            "/v2/objects",
            "/v2/objects/o1/attributes",
            "/v2/objects/o1/attributes/b/options",
        ]
        assert [row["option_id"] for row in result.rows] == ["v2"]
