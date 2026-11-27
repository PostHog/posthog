from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional

from unittest.mock import patch

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.sources.sdk import Resource
from products.warehouse_sources.sources.sdk.testing import (
    RunStopped,
    ScriptedResponse,
    SourceDriver,
    activate_safe_point,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.sources.thinkific_courses._config import ThinkificCoursesSourceConfig
from products.warehouse_sources.sources.thinkific_courses.settings import THINKIFIC_COURSES_ENDPOINTS
from products.warehouse_sources.sources.thinkific_courses.source import ThinkificCoursesSource
from products.warehouse_sources.sources.thinkific_courses.thinkific_courses import (
    ThinkificCoursesResumeConfig,
    _format_incremental_date,
    validate_credentials,
)


def _driver() -> SourceDriver:
    return SourceDriver(ThinkificCoursesSource(), ThinkificCoursesSourceConfig(api_key="key", subdomain="sub"))


def _response(items: Optional[list[dict[str, Any]]], total_pages: int = 1) -> ScriptedResponse:
    return ScriptedResponse(json={"items": items or [], "meta": {"pagination": {"total_pages": total_pages}}})


def _error_response(status: int) -> ScriptedResponse:
    return ScriptedResponse(status=status, json={"error": "Authentication Error"})


class TestFormatIncrementalDate:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 3, 4, 23, 58, tzinfo=UTC), "2026-03-04"),
            ("naive_datetime", datetime(2026, 3, 4, 1, 0), "2026-03-04"),
            ("date", date(2026, 3, 4), "2026-03-04"),
            ("iso_string", "2026-03-04T10:00:00Z", "2026-03-04"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_date(value) == expected


class TestPagination:
    def test_fresh_run_paginates_and_saves_after_each_non_terminal_page(self) -> None:
        responses = [
            _response([{"id": 1}], total_pages=3),
            _response([{"id": 2}], total_pages=3),
            _response([{"id": 3}], total_pages=3),
        ]
        result = _driver().run("courses", responses)

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}, {"id": 3}]

        # First request starts at page=1 with the configured limit; later requests advance by page.
        assert result.params("page") == ["1", "2", "3"]
        assert result.params("limit") == ["100", "100", "100"]

        # State saved after each non-terminal page (points at the next page); the last page saves nothing.
        assert result.saved_states == [
            ThinkificCoursesResumeConfig(next_page=2),
            ThinkificCoursesResumeConfig(next_page=3),
        ]

    def test_resume_starts_from_saved_page(self) -> None:
        result = _driver().run(
            "courses", [_response([{"id": 99}], total_pages=5)], resume_state=ThinkificCoursesResumeConfig(next_page=5)
        )

        assert result.raised is None
        assert result.rows == [{"id": 99}]
        assert result.params("page") == ["5"]


class TestIncrementalFilter:
    @parameterized.expand(
        [
            # Filter added only when all three hold: endpoint supports it, flag on, cursor present.
            ("enrollments_all_conditions", "enrollments", True, datetime(2026, 3, 4, tzinfo=UTC), True),
            ("enrollments_flag_off", "enrollments", False, datetime(2026, 3, 4, tzinfo=UTC), False),
            ("enrollments_cursor_missing", "enrollments", True, None, False),
            # Full-refresh endpoints never get the filter, even with flag + cursor set.
            ("courses_never", "courses", True, datetime(2026, 3, 4, tzinfo=UTC), False),
        ]
    )
    def test_filter_only_when_all_conditions_hold(
        self, _name: str, endpoint: str, should_use: bool, value: Any, expected_present: bool
    ) -> None:
        result = _driver().run(
            endpoint,
            [_response([{"id": 1}], total_pages=1)],
            should_use_incremental_field=should_use,
            db_incremental_field_last_value=value,
        )
        assert result.raised is None
        assert (result.requests[0].param("query[updated_on_or_after]") is not None) is expected_present
        if expected_present:
            assert result.requests[0].param("query[updated_on_or_after]") == "2026-03-04"


class TestFanout:
    def test_fanout_resume_skips_completed_parents(self) -> None:
        responses = [
            _response([{"id": 11}, {"id": 22}], total_pages=1),  # parent: courses
            _response([{"id": 2, "rating": 4}], total_pages=1),  # reviews for course 22 only
        ]
        result = _driver().run(
            "course_reviews",
            responses,
            resume_state=ThinkificCoursesResumeConfig(
                completed=["/course_reviews?course_id=11"], current=None, child_state=None
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": 2, "rating": 4, "course_id": 22}]
        assert result.paths == ["/api/public/v1/courses", "/api/public/v1/course_reviews"]
        assert result.requests[1].param("course_id") == "22"
        assert len(result.requests) == 2

    @parameterized.expand(
        [
            (
                "chapters_per_course",
                "chapters",
                [{"id": 11}, {"id": 22}],
                [[{"id": 1, "name": "Intro"}], [{"id": 2, "name": "Basics"}]],
                ["/api/public/v1/courses", "/api/public/v1/courses/11/chapters", "/api/public/v1/courses/22/chapters"],
                [{"id": 1, "name": "Intro", "course_id": 11}, {"id": 2, "name": "Basics", "course_id": 22}],
            ),
            (
                # One contents request per entry in each course's chapter_ids; a course with an empty
                # or null chapter_ids list makes no request at all.
                "contents_per_chapter_id",
                "contents",
                [{"id": 11, "chapter_ids": [5, 6]}, {"id": 22, "chapter_ids": []}, {"id": 33, "chapter_ids": None}],
                [[{"id": 50, "chapter_id": 5}], [{"id": 60, "chapter_id": 6}, {"id": 61, "chapter_id": 6}]],
                ["/api/public/v1/courses", "/api/public/v1/chapters/5/contents", "/api/public/v1/chapters/6/contents"],
                [
                    {"id": 50, "chapter_id": 5, "course_id": 11},
                    {"id": 60, "chapter_id": 6, "course_id": 11},
                    {"id": 61, "chapter_id": 6, "course_id": 11},
                ],
            ),
            (
                "products_per_collection",
                "collection_products",
                [{"id": 7}],
                [[{"id": 100, "name": "Course A"}, {"id": 101, "name": "Bundle B"}]],
                ["/api/public/v1/collections", "/api/public/v1/collections/7/products"],
                [
                    {"id": 100, "name": "Course A", "collection_id": 7},
                    {"id": 101, "name": "Bundle B", "collection_id": 7},
                ],
            ),
            (
                "related_products_per_product",
                "related_products",
                [{"id": 21, "productable_id": 31}, {"id": 22, "productable_id": 32}],
                [[{"id": 23, "productable_id": 33}], [{"id": 23, "productable_id": 33}]],
                ["/api/public/v1/products", "/api/public/v1/products/21/related", "/api/public/v1/products/22/related"],
                [
                    {"id": 23, "productable_id": 33, "product_id": 21},
                    {"id": 23, "productable_id": 33, "product_id": 22},
                ],
            ),
        ]
    )
    def test_fanout_requests_each_parent_and_tags_rows_with_parent_id(
        self,
        _name: str,
        endpoint: str,
        parents: list[dict[str, Any]],
        child_pages: list[list[dict[str, Any]]],
        expected_paths: list[str],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        responses = [_response(parents), *[_response(page) for page in child_pages]]
        result = _driver().run(endpoint, responses)

        assert result.raised is None
        assert result.paths == expected_paths
        assert result.rows == expected_rows

    @parameterized.expand(
        [
            ("bundle_courses", "/bundles/31/courses", [{"id": 42}], None, True),
            ("bundle_enrollments", "/bundles/31/enrollments", [{"id": 42}], 3, True),
            ("related_products", "/products/21/related", [{"id": 42}], 3, True),
            ("related_products", "/products/21/related", [{"id": 42}], 2, False),
            ("related_products", "/products/21/related", [], None, False),
        ]
    )
    def test_child_page_limit(
        self, endpoint: str, child_path: str, last_page: list[dict[str, Any]], total_pages: int | None, fails: bool
    ) -> None:
        last_response = (
            _response(last_page, total_pages=total_pages)
            if total_pages is not None
            else ScriptedResponse(json={"items": last_page})
        )
        with patch("products.warehouse_sources.sources.thinkific_courses.thinkific_courses._MAX_FANOUT_CHILD_PAGES", 2):
            result = _driver().run(
                endpoint,
                [
                    _response([{"id": 21, "productable_type": "Bundle", "productable_id": 31}]),
                    _response([{"id": 41}], total_pages=2),
                    last_response,
                ],
            )

        assert result.paths == ["/api/public/v1/products", *[f"/api/public/v1{child_path}"] * 2]
        assert result.params("page") == ["1", "1", "2"]
        if fails:
            assert isinstance(result.raised, RuntimeError)
            assert "exceeded the 2-page limit per parent" in str(result.raised)
        else:
            assert result.raised is None
            assert [row["id"] for row in result.rows] == [41, *[row["id"] for row in last_page]]

    def test_contents_resume_skips_completed_chapters(self) -> None:
        responses = [
            _response([{"id": 11, "chapter_ids": [5, 6]}]),
            _response([{"id": 60, "chapter_id": 6}]),
        ]
        result = _driver().run(
            "contents",
            responses,
            resume_state=ThinkificCoursesResumeConfig(
                completed=["/chapters/5/contents"], current=None, child_state=None
            ),
        )

        assert result.raised is None
        assert result.paths == ["/api/public/v1/courses", "/api/public/v1/chapters/6/contents"]
        assert result.rows == [{"id": 60, "chapter_id": 6, "course_id": 11}]


class TestBundleTables:
    @parameterized.expand(
        [
            ("courses", "bundle_courses", None, None),
            ("enrollments_backfill", "bundle_enrollments", None, None),
            ("enrollments_incremental", "bundle_enrollments", "2026-04-01T10:00:00Z", "2026-03-31"),
        ]
    )
    def test_uses_bundle_id_and_filters_only_child_pages(
        self, _name: str, endpoint: str, watermark: str | None, expected_filter: str | None
    ) -> None:
        responses = [
            _response(
                [
                    {"id": 8, "productable_type": "Course", "productable_id": 82},
                    {"id": 9, "productable_type": "Bundle", "productable_id": 93},
                ]
            ),
            _response([{"id": 71}], total_pages=2),
            _response([{"id": 72}], total_pages=2),
        ]
        result = _driver().run(
            endpoint,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        child_path = f"/api/public/v1/bundles/93/{endpoint.removeprefix('bundle_')}"
        assert result.paths == ["/api/public/v1/products", child_path, child_path]
        assert result.params("page") == ["1", "1", "2"]
        assert result.params("query[updated_after]") == [None, expected_filter, expected_filter]
        assert result.rows == [{"id": 71, "bundle_id": 93}, {"id": 72, "bundle_id": 93}]

    def test_resumed_bundle_enrollments_can_yield_older_updates(self) -> None:
        products = _response(
            [
                {"id": 21, "productable_type": "Bundle", "productable_id": 31},
                {"id": 22, "productable_type": "Bundle", "productable_id": 32},
            ]
        )
        newer = {"id": 41, "updated_at": "2026-04-03T10:00:00Z"}
        older = {"id": 42, "updated_at": "2026-04-02T10:00:00Z"}
        first = _driver().run(
            "bundle_enrollments", [products, _response([newer]), RunStopped("handoff")], incremental_field="updated_at"
        )
        assert isinstance(first.raised, RunStopped)
        assert first.rows == [{**newer, "bundle_id": 31}]
        assert first.final_state is not None

        resumed = _driver().run(
            "bundle_enrollments",
            [products, _response([older])],
            resume_state=first.final_state,
            incremental_field="updated_at",
        )
        assert resumed.raised is None
        assert resumed.paths == ["/api/public/v1/products", "/api/public/v1/bundles/32/enrollments"]
        assert resumed.rows == [{**older, "bundle_id": 32}]
        assert resumed.response is not None
        assert resumed.response.sort_mode is None


class TestGroupAnalysts:
    def test_expands_user_ids_and_continues_past_empty_groups(self) -> None:
        result = _driver().run(
            "group_analysts",
            [
                _response([{"id": 3}, {"id": 4}, {"id": 5}]),
                ScriptedResponse(json={"group_analysts": [11, 12]}),
                ScriptedResponse(json={"group_analysts": []}),
                ScriptedResponse(json={"group_analysts": [11]}),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/api/public/v1/groups",
            "/api/public/v1/groups/3/analysts",
            "/api/public/v1/groups/4/analysts",
            "/api/public/v1/groups/5/analysts",
        ]
        assert result.params("page") == ["1", None, None, None]
        assert result.params("limit") == ["100", None, None, None]
        assert result.rows == [
            {"group_id": 3, "user_id": 11},
            {"group_id": 3, "user_id": 12},
            {"group_id": 5, "user_id": 11},
        ]

    def test_resume_skips_the_group_written_before_interruption(self) -> None:
        source = ThinkificCoursesSource()
        config = ThinkificCoursesSourceConfig(api_key="key", subdomain="sub")
        inputs = source_inputs("group_analysts")
        groups = _response([{"id": 3}, {"id": 4}])

        with scripted_network([groups, ScriptedResponse(json={"group_analysts": [11, 12]})]):
            manager = source.get_resumable_source_manager(inputs)
            items = source.source_for_pipeline(config, manager, inputs).items()
            assert isinstance(items, Iterable)
            with activate_safe_point(manager.confirm, covers_framework_checkpoints=isinstance(items, Resource)):
                pages = iter(items)
                assert next(pages) == [{"group_id": 3, "user_id": 11}, {"group_id": 3, "user_id": 12}]
                manager.confirm()
                manager.commit()
                checkpoint = manager.load_state()

        assert checkpoint is not None
        resumed = _driver().run(
            "group_analysts", [groups, ScriptedResponse(json={"group_analysts": [13]})], resume_state=checkpoint
        )
        assert resumed.raised is None
        assert resumed.paths == ["/api/public/v1/groups", "/api/public/v1/groups/4/analysts"]
        assert resumed.rows == [{"group_id": 4, "user_id": 13}]


class TestErrorHandling:
    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    def test_auth_error_raises_matchable_http_error(self, _name: str, status: int, reason: str) -> None:
        # A 401/403 must surface as an HTTPError whose message carries the status and host, so
        # get_non_retryable_errors can substring-match it and stop the sync loud.
        result = _driver().run("courses", [_error_response(status)])
        assert isinstance(result.raised, HTTPError)
        message = str(result.raised)
        assert f"{status}" in message
        assert reason in message
        assert "api.thinkific.com" in message


class TestSourceResponse:
    @parameterized.expand(list(THINKIFIC_COURSES_ENDPOINTS.keys()))
    def test_every_endpoint_builds_a_response_with_its_declared_keys(self, endpoint: str) -> None:
        config = THINKIFIC_COURSES_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_response([])])
        assert result.raised is None
        resp = result.response
        assert resp is not None
        assert resp.name == endpoint
        assert resp.primary_keys == config.primary_keys
        assert callable(resp.items)

    @parameterized.expand([("enrollments",), ("users",)])
    def test_partitioned_endpoint_partitions_by_created_at(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_response([])])
        assert result.raised is None
        resp = result.response
        assert resp is not None
        assert resp.partition_mode == "datetime"
        assert resp.partition_keys == ["created_at"]
        assert resp.partition_format == "month"

    @parameterized.expand(
        [
            ("course_reviews", ["course_id", "id"]),
            ("coupons", ["promotion_id", "id"]),
            ("chapters", ["course_id", "id"]),
            ("contents", ["chapter_id", "id"]),
            ("collection_products", ["collection_id", "id"]),
        ]
    )
    def test_fanout_children_use_composite_primary_keys(self, endpoint: str, expected: list[str]) -> None:
        # Child ids aren't documented as globally unique, so the parent id must stay in the key —
        # dropping it seeds duplicate rows and every later merge multi-matches them.
        result = _driver().run(endpoint, [_response([])])
        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("forbidden", 403, False, 403),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool, expected_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, code = validate_credentials("key", "sub")
        assert is_valid is expected_valid
        assert code == expected_code
        assert network.requests_log[0].path == "/api/public/v1/courses"
        assert network.requests_log[0].headers["x-auth-api-key"] == "key"

    def test_probe_disables_redirects_and_sample_capture_to_protect_customer_data(self) -> None:
        # The X-Auth-API-Key header rides on the probe, so redirects are pinned off to stop a redirect
        # replaying the key off-host. A successful /courses probe also returns real customer data
        # (student names, free-text notes), so capture is off to keep that body out of HTTP sample storage.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("key", "sub")
        assert network.session_options[0]["allow_redirects"] is False
        assert network.session_options[0]["capture"] is False


class TestPipelineSessionCapture:
    def test_client_config_disables_sample_capture_and_pins_redirects(self) -> None:
        # Thinkific rows carry student names/emails and free-text review and coupon notes the name-based
        # scrubbers can't recognise, so the pipeline session must be built with capture off (bodies stay
        # out of HTTP sample storage), redirects pinned off (the key can't be replayed off-host), and the
        # key registered for log redaction.
        result = _driver().run("courses", [_response([])])
        assert result.raised is None
        assert result.session_options[0]["capture"] is False
        assert result.session_options[0]["allow_redirects"] is False
        assert result.session_options[0]["redact_values"] == ("key",)
