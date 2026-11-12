from datetime import UTC, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.sources.circle_so._config import CircleSoSourceConfig
from products.warehouse_sources.sources.circle_so.circle_so import CircleSoResumeConfig
from products.warehouse_sources.sources.circle_so.source import CircleSoSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, route

BASE_PATH = "/api/admin/v2"


def _driver() -> SourceDriver:
    return SourceDriver(CircleSoSource(), CircleSoSourceConfig(api_token="token"))


def _page(records: list[dict[str, Any]] | None, has_next_page: bool | None = False) -> ScriptedResponse:
    body: dict[str, Any] = {}
    if records is not None:
        body["records"] = records
    if has_next_page is not None:
        body["has_next_page"] = has_next_page
    return ScriptedResponse(json=body)


class TestListPagination:
    def test_walks_pages_until_has_next_page_is_false(self) -> None:
        result = _driver().run(
            "community_members",
            [_page([{"id": 1}, {"id": 2}], has_next_page=True), _page([{"id": 3}], has_next_page=False)],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert result.urls[0].split("?")[0] == "https://app.circle.so/api/admin/v2/community_members"
        assert result.queries == [
            {"per_page": ("100",), "status": ("all",), "page": ("1",)},
            {"per_page": ("100",), "status": ("all",), "page": ("2",)},
        ]
        assert result.requests[0].headers["authorization"] == "Bearer token"

    @parameterized.expand(
        [
            # The flag says more pages follow, but the page is empty: stop instead of paging on.
            ("flag_true_on_empty_page", [_page([{"id": 1}], has_next_page=True), _page([], has_next_page=True)]),
            ("flag_missing", [_page([{"id": 1}], has_next_page=None), _page([], has_next_page=None)]),
        ]
    )
    def test_empty_page_ends_the_walk(self, _name: str, pages: list[ScriptedResponse]) -> None:
        result = _driver().run("tagged_members", pages)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1]
        assert result.params("page") == ["1", "2"]

    def test_missing_records_key_fails_loud(self) -> None:
        result = _driver().run("spaces", [_page(None)])

        assert isinstance(result.raised, ValueError)
        assert "data_selector" in str(result.raised)


class TestListResume:
    def test_stages_next_page_before_each_page_including_the_last(self) -> None:
        result = _driver().run(
            "posts",
            [_page([{"id": 1}], has_next_page=True), _page([{"id": 2}], has_next_page=False)],
        )

        assert result.raised is None
        # The last page stages the page after it, so a resumed attempt reads one empty page
        # instead of loading the last page again.
        assert result.committed_states == [CircleSoResumeConfig(next_page=2), CircleSoResumeConfig(next_page=3)]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "posts",
            [_page([{"id": 7}], has_next_page=True), _page([{"id": 8}], has_next_page=False)],
            resume_state=CircleSoResumeConfig(next_page=3),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [7, 8]
        assert result.params("page") == ["3", "4"]
        assert result.committed_states[-1] == CircleSoResumeConfig(next_page=5)


class TestIncrementalCharges:
    @parameterized.expand(
        [
            ("incremental_with_watermark", True, datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC), "2026-03-04T05:06:07Z"),
            ("incremental_first_sync", True, None, None),
            ("full_refresh", False, datetime(2026, 3, 4, tzinfo=UTC), None),
        ]
    )
    def test_request_shaping(
        self, _name: str, incremental: bool, last_value: datetime | None, expected_filter: str | None
    ) -> None:
        result = _driver().run(
            "community_member_charges",
            [_page([{"id": 1, "created_at": "2026-03-05T00:00:00.000Z"}])],
            incremental_field="created_at",
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.params("created_at_gte") == [expected_filter]
        # The ascending sort on created_at is what makes sort_mode="asc" true.
        assert result.params("sort") == ["created_at"]
        assert result.params("direction") == ["asc"]
        assert result.response is not None
        assert result.response.sort_mode == ("asc" if incremental else None)


class TestFanout:
    @parameterized.expand(
        [
            ("space_members", "spaces", "/space_members", "space_id", {"sort": "oldest"}, {"status": "all"}),
            (
                "space_group_members",
                "space_groups",
                "/space_group_members",
                "space_group_id",
                {},
                {"status": "all"},
            ),
            ("event_attendees", "events", "/event_attendees", "event_id", {"sort": "oldest"}, {}),
            ("form_submissions", "forms", None, "form_id", {}, {}),
        ]
    )
    def test_walks_every_page_of_every_parent(
        self,
        endpoint: str,
        parent: str,
        child_path: str | None,
        parent_key: str,
        parent_params: dict[str, str],
        child_params: dict[str, str],
    ) -> None:
        def child(parent_id: int) -> str:
            return f"{BASE_PATH}/forms/{parent_id}/submissions" if child_path is None else f"{BASE_PATH}{child_path}"

        def child_query(parent_id: int, page: int) -> dict[str, tuple[str, ...]]:
            query = {"per_page": ("100",), **{k: (v,) for k, v in child_params.items()}, "page": (str(page),)}
            if child_path is not None:
                query[parent_key] = (str(parent_id),)
            return query

        responses: dict[str, list[ScriptedResponse]] = {
            f"{BASE_PATH}/{parent}": [_page([{"id": 10}, {"id": 20}])],
        }
        if child_path is None:
            responses[child(10)] = [_page([{"id": 1}], has_next_page=True), _page([{"id": 2}])]
            responses[child(20)] = [_page([{"id": 1}])]
        else:
            # Both parents share one path; the query string tells them apart.
            responses[child(10)] = [_page([{"id": 1}], has_next_page=True), _page([{"id": 2}]), _page([{"id": 1}])]

        result = _driver().run(endpoint, route(responses))

        assert result.raised is None
        assert [(row[parent_key], row["id"]) for row in result.rows] == [(10, 1), (10, 2), (20, 1)]
        assert all(f"_{parent}_id" not in row for row in result.rows)
        assert result.paths == [f"{BASE_PATH}/{parent}", child(10), child(10), child(20)]
        assert result.queries[0] == {
            "per_page": ("100",),
            **{k: (v,) for k, v in parent_params.items()},
            "page": ("1",),
        }
        assert result.queries[1:] == [child_query(10, 1), child_query(10, 2), child_query(20, 1)]
        assert result.response is not None
        assert result.response.primary_keys == [parent_key, "id"]

    def test_skips_a_parent_deleted_before_its_child_fetch(self) -> None:
        result = _driver().run(
            "form_submissions",
            route(
                {
                    f"{BASE_PATH}/forms": [_page([{"id": 10}, {"id": 20}])],
                    f"{BASE_PATH}/forms/10/submissions": [ScriptedResponse(status=404)],
                    f"{BASE_PATH}/forms/20/submissions": [_page([{"id": 1}])],
                }
            ),
        )

        assert result.raised is None
        assert [(row["form_id"], row["id"]) for row in result.rows] == [(20, 1)]

    def test_resume_skips_parents_already_read(self) -> None:
        result = _driver().run(
            "form_submissions",
            route(
                {
                    f"{BASE_PATH}/forms": [_page([{"id": 10}, {"id": 20}])],
                    f"{BASE_PATH}/forms/20/submissions": [_page([{"id": 3}])],
                }
            ),
            resume_state=CircleSoResumeConfig(
                fanout_state={"completed": ["/forms/10/submissions"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.paths == [f"{BASE_PATH}/forms", f"{BASE_PATH}/forms/20/submissions"]
        assert [(row["form_id"], row["id"]) for row in result.rows] == [(20, 3)]
        assert result.committed_states
