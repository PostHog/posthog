from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest

from products.warehouse_sources.sources.planning_center._config import PlanningCenterSourceConfig
from products.warehouse_sources.sources.planning_center.planning_center import (
    INITIAL_UPDATED_AT,
    UPDATED_AT_FILTER_PARAM,
    PlanningCenterResumeConfig,
    flatten_resource,
    format_updated_at,
)
from products.warehouse_sources.sources.planning_center.source import PlanningCenterSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, route


def _driver() -> SourceDriver:
    return SourceDriver(
        PlanningCenterSource(), PlanningCenterSourceConfig(application_id="app-id", secret="pat-secret")
    )


def _resource(resource_id: str, **attributes: Any) -> dict[str, Any]:
    return {"type": "Thing", "id": resource_id, "attributes": attributes, "relationships": {}, "links": {}}


def _page(items: list[dict[str, Any]], total_count: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={"links": {}, "data": items, "included": [], "meta": {"total_count": total_count, "count": len(items)}}
    )


class TestPagination:
    def test_walks_offset_pages_to_the_terminal_page(self) -> None:
        first = [_resource(str(i), created_at="2025-01-01T00:00:00Z") for i in range(100)]
        last = [_resource("100", created_at="2025-01-02T00:00:00Z")]

        result = _driver().run("people", [_page(first, 101), _page(last, 101)])

        assert result.raised is None
        assert result.paths == ["/people/v2/people", "/people/v2/people"]
        assert result.params("offset") == ["0", "100"]
        assert result.params("per_page") == ["100", "100"]
        assert result.params("order") == ["created_at", "created_at"]
        assert [request.headers["x-pco-api-version"] for request in result.requests] == ["2026-10-05"] * 2
        assert len(result.rows) == 101
        assert result.rows[-1] == {"id": "100", "created_at": "2025-01-02T00:00:00Z"}
        assert result.committed_states == [PlanningCenterResumeConfig(next_offset=100)]

    def test_incremental_walk_seeks_on_updated_at_of_the_last_row(self) -> None:
        first = [_resource(str(i), updated_at=f"2026-02-01T00:00:{i % 60:02d}Z") for i in range(98)]
        first += [_resource(str(i), updated_at="2026-02-02T00:00:00Z") for i in range(98, 100)]
        ties = [_resource(str(i), updated_at="2026-02-02T00:00:00Z") for i in range(100, 200)]
        last = [_resource("200", updated_at="2026-02-03T00:00:00Z")]

        result = _driver().run(
            "people",
            [_page(first, 201), _page(ties, 201), _page(last, 201)],
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params(UPDATED_AT_FILTER_PARAM) == [
            "2026-01-01T00:00:00Z",
            "2026-02-02T00:00:00Z",
            "2026-02-02T00:00:00Z",
        ]
        assert result.params("offset") == ["0", "2", "102"]
        assert result.params("order") == ["updated_at"] * 3
        assert len(result.rows) == 201
        assert result.committed_states == [
            PlanningCenterResumeConfig(next_offset=2, next_updated_at="2026-02-02T00:00:00Z"),
            PlanningCenterResumeConfig(next_offset=102, next_updated_at="2026-02-02T00:00:00Z"),
        ]

    @pytest.mark.parametrize(
        ("inputs", "resume_state", "expected_filter", "expected_offset"),
        [
            ({}, PlanningCenterResumeConfig(next_offset=200), None, "200"),
            (
                {
                    "incremental_field": "updated_at",
                    "db_incremental_field_last_value": datetime(2026, 1, 1, tzinfo=UTC),
                },
                PlanningCenterResumeConfig(next_offset=3, next_updated_at="2026-02-02T00:00:00Z"),
                "2026-02-02T00:00:00Z",
                "3",
            ),
        ],
    )
    def test_resume_starts_at_the_saved_position(
        self,
        inputs: dict[str, Any],
        resume_state: PlanningCenterResumeConfig,
        expected_filter: str | None,
        expected_offset: str,
    ) -> None:
        result = _driver().run("people", [_page([_resource("201")], 201)], resume_state=resume_state, **inputs)

        assert result.params(UPDATED_AT_FILTER_PARAM) == [expected_filter]
        assert result.params("offset") == [expected_offset]
        assert [row["id"] for row in result.rows] == ["201"]


class TestRequestShaping:
    @pytest.mark.parametrize(
        ("schema", "inputs", "path", "version", "expected_filter", "expected_order", "expected_sort_mode"),
        [
            (
                "people",
                {"incremental_field": "updated_at", "db_incremental_field_last_value": datetime(2026, 3, 4, 5, 6, 7)},
                "/people/v2/people",
                "2026-10-05",
                "2026-03-04T05:06:07Z",
                "updated_at",
                "asc",
            ),
            (
                "donations",
                {"incremental_field": "updated_at"},
                "/giving/v2/donations",
                "2019-10-18",
                INITIAL_UPDATED_AT,
                "updated_at",
                "asc",
            ),
            (
                "people",
                {"incremental_field": "updated_at", "should_use_incremental_field": False},
                "/people/v2/people",
                "2026-10-05",
                None,
                "created_at",
                None,
            ),
            (
                "calendar_events",
                {
                    "incremental_field": "updated_at",
                    "db_incremental_field_last_value": datetime(2026, 1, 1, tzinfo=UTC),
                },
                "/calendar/v2/events",
                "2026-06-22",
                "2026-01-01T00:00:00Z",
                None,
                None,
            ),
            ("group_memberships", {}, "/groups/v2/memberships", "2026-11-10", None, None, None),
            ("check_in_events", {}, "/check-ins/v2/events", "2025-05-28", None, "created_at", None),
        ],
    )
    def test_request_matches_the_sync_mode(
        self,
        schema: str,
        inputs: dict[str, Any],
        path: str,
        version: str,
        expected_filter: str | None,
        expected_order: str | None,
        expected_sort_mode: str | None,
    ) -> None:
        result = _driver().run(schema, [_page([_resource("1")], 1)], **inputs)

        assert result.raised is None
        assert result.paths == [path]
        assert result.requests[0].headers["x-pco-api-version"] == version
        assert result.params(UPDATED_AT_FILTER_PARAM) == [expected_filter]
        assert result.params("order") == [expected_order]
        assert result.response is not None
        assert result.response.sort_mode == expected_sort_mode


class TestPlansFanOut:
    def test_fetches_plans_per_service_type_with_the_parent_id_on_each_row(self) -> None:
        service_types = _page([_resource("st1"), _resource("st2")], 2)
        result = _driver().run(
            "plans",
            route(
                {
                    "/services/v2/service_types": [service_types],
                    "/services/v2/service_types/st1/plans": [
                        _page([_resource("p1", title="Sunday", updated_at="2026-02-01T00:00:00Z")], 1)
                    ],
                    "/services/v2/service_types/st2/plans": [
                        _page([_resource("p2", title="Youth", updated_at="2026-02-02T00:00:00Z")], 1)
                    ],
                }
            ),
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2026, 1, 15, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.paths == [
            "/services/v2/service_types",
            "/services/v2/service_types/st1/plans",
            "/services/v2/service_types/st2/plans",
        ]
        assert result.params(UPDATED_AT_FILTER_PARAM) == [None, "2026-01-15T00:00:00Z", "2026-01-15T00:00:00Z"]
        assert result.params("order") == [None, "updated_at", "updated_at"]
        assert {request.headers["x-pco-api-version"] for request in result.requests} == {"2018-11-01"}
        assert [(row["service_type_id"], row["id"], row["title"]) for row in result.rows] == [
            ("st1", "p1", "Sunday"),
            ("st2", "p2", "Youth"),
        ]
        assert result.response is not None
        assert result.response.sort_mode is None


class TestFlattenResource:
    @pytest.mark.parametrize(
        ("item", "expected"),
        [
            (
                {
                    "type": "Email",
                    "id": "1",
                    "attributes": {"address": "a@example.com", "primary": True},
                    "relationships": {"person": {"data": {"type": "Person", "id": "42"}}},
                    "links": {"self": "https://api.planningcenteronline.com/people/v2/emails/1"},
                },
                {"id": "1", "address": "a@example.com", "primary": True, "person_id": "42"},
            ),
            (
                {
                    "type": "Household",
                    "id": "2",
                    "attributes": {},
                    "relationships": {
                        "people": {"data": [{"type": "Person", "id": "7"}, {"type": "Person", "id": "8"}]},
                        "primary_contact": {"data": None},
                    },
                },
                {"id": "2", "people_ids": ["7", "8"], "primary_contact_id": None},
            ),
            (
                {
                    "type": "Note",
                    "id": "3",
                    "attributes": {"person_id": 42},
                    "relationships": {
                        "person": {"data": {"type": "Person", "id": "42"}},
                        "created_by": {"links": {"related": "https://example.com"}},
                    },
                },
                {"id": "3", "person_id": 42},
            ),
            (
                {"id": "p1", "service_type_id": "st1", "attributes": {"title": "Sunday"}, "relationships": None},
                {"id": "p1", "service_type_id": "st1", "title": "Sunday"},
            ),
            (
                {
                    "id": "p2",
                    "service_type_id": "st1",
                    "attributes": {},
                    "relationships": {"service_type": {"data": {"type": "ServiceType", "id": "st9"}}},
                },
                {"id": "p2", "service_type_id": "st1"},
            ),
        ],
    )
    def test_flattens_json_api_resources(self, item: dict[str, Any], expected: dict[str, Any]) -> None:
        assert flatten_resource(item) == expected


class TestFormatUpdatedAt:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 3, 4, 5, 6, 7, 890000), "2026-03-04T05:06:07Z"),
            (datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone(timedelta(hours=-5))), "2026-03-04T10:06:07Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("2026-03-04T05:06:07Z", "2026-03-04T05:06:07Z"),
        ],
    )
    def test_formats_a_full_utc_timestamp(self, value: Any, expected: str) -> None:
        assert format_updated_at(value) == expected
