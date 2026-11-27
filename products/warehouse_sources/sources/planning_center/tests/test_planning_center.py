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
            ("signups", {}, "/registrations/v2/signups", "2025-05-01", None, "created_at", None),
            ("attendees", {}, "/registrations/v2/attendees", "2025-05-01", None, "created_at", None),
            ("marital_statuses", {}, "/people/v2/marital_statuses", "2026-10-05", None, "sequence", None),
            ("name_prefixes", {}, "/people/v2/name_prefixes", "2026-10-05", None, "value", None),
            ("episodes", {}, "/publishing/v2/episodes", "2024-03-25", None, None, None),
            (
                "note_categories",
                {
                    "incremental_field": "updated_at",
                    "db_incremental_field_last_value": datetime(2026, 1, 1, tzinfo=UTC),
                },
                "/people/v2/note_categories",
                "2026-10-05",
                "2026-01-01T00:00:00Z",
                "updated_at",
                "asc",
            ),
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


class TestSingleHopFanOut:
    @pytest.mark.parametrize(
        ("schema", "parent_path", "child", "parent_key", "inputs", "expected_filter", "expected_order"),
        [
            (
                "workflow_steps",
                "/people/v2/workflows",
                "steps",
                "workflow_id",
                {
                    "incremental_field": "updated_at",
                    "db_incremental_field_last_value": datetime(2026, 1, 15, tzinfo=UTC),
                },
                "2026-01-15T00:00:00Z",
                "updated_at",
            ),
            ("workflow_steps", "/people/v2/workflows", "steps", "workflow_id", {}, None, "created_at"),
            ("workflow_cards", "/people/v2/workflows", "cards", "workflow_id", {}, None, "created_at"),
            (
                "form_submissions",
                "/people/v2/forms",
                "form_submissions",
                "form_id",
                {
                    "incremental_field": "updated_at",
                    "db_incremental_field_last_value": datetime(2026, 1, 15, tzinfo=UTC),
                },
                "2026-01-15T00:00:00Z",
                "updated_at",
            ),
            ("form_fields", "/people/v2/forms", "fields", "form_id", {}, None, "sequence"),
        ],
    )
    def test_fetches_children_per_parent_with_the_parent_id_on_each_row(
        self,
        schema: str,
        parent_path: str,
        child: str,
        parent_key: str,
        inputs: dict[str, Any],
        expected_filter: str | None,
        expected_order: str,
    ) -> None:
        result = _driver().run(
            schema,
            route(
                {
                    parent_path: [_page([_resource("w1"), _resource("w2")], 2)],
                    f"{parent_path}/w1/{child}": [_page([_resource("c1", updated_at="2026-02-01T00:00:00Z")], 1)],
                    f"{parent_path}/w2/{child}": [_page([_resource("c2", updated_at="2026-02-02T00:00:00Z")], 1)],
                }
            ),
            **inputs,
        )

        assert result.raised is None
        assert result.paths == [parent_path, f"{parent_path}/w1/{child}", f"{parent_path}/w2/{child}"]
        assert result.params(UPDATED_AT_FILTER_PARAM) == [None, expected_filter, expected_filter]
        assert result.params("order")[1:] == [expected_order, expected_order]
        assert [(row[parent_key], row["id"]) for row in result.rows] == [("w1", "c1"), ("w2", "c2")]


class TestSchedulesFanOut:
    def test_fetches_every_schedule_of_each_services_person_and_skips_a_removed_person(self) -> None:
        schedule = {
            **_resource("s1", status="D", team_name="Band"),
            "relationships": {"person": {"data": {"type": "Person", "id": "p1"}}},
        }
        result = _driver().run(
            "schedules",
            route(
                {
                    "/services/v2/people": [_page([_resource("p1"), _resource("p2")], 2)],
                    "/services/v2/people/p1/schedules": [_page([schedule], 1)],
                    "/services/v2/people/p2/schedules": [
                        ScriptedResponse(status=404, json={"errors": [{"status": "404"}]})
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.params("filter") == [
            None,
            "all,with_declined,not_across_organizations",
            "all,with_declined,not_across_organizations",
        ]
        assert {request.headers["x-pco-api-version"] for request in result.requests} == {"2018-11-01"}
        assert result.rows == [{"id": "s1", "person_id": "p1", "status": "D", "team_name": "Band"}]

    def test_resume_starts_the_people_listing_at_the_saved_page(self) -> None:
        result = _driver().run(
            "schedules",
            route(
                {
                    "/services/v2/people": [_page([_resource("p200")], 201)],
                    "/services/v2/people/p200/schedules": [_page([_resource("s200")], 1)],
                }
            ),
            resume_state=PlanningCenterResumeConfig(fanout_state={"parent": {"offset": 200}}),
        )

        assert result.raised is None
        assert result.params("offset")[0] == "200"
        assert result.params("order")[0] == "created_at"
        assert [(row["person_id"], row["id"]) for row in result.rows] == [("p200", "s200")]


class TestIncludedResources:
    @pytest.mark.parametrize(
        ("schema", "include", "resource_type", "relationship_data"),
        [
            (
                "donation_designations",
                "designations",
                "Designation",
                lambda child_id: {"designations": {"data": [{"type": "Designation", "id": child_id}]}},
            ),
            (
                "donation_refunds",
                "refund",
                "Refund",
                lambda child_id: {"refund": {"data": {"type": "Refund", "id": child_id}}},
            ),
        ],
    )
    def test_walks_donation_pages_and_reads_the_included_children(
        self, schema: str, include: str, resource_type: str, relationship_data: Any
    ) -> None:
        def page(donation_ids: list[str]) -> ScriptedResponse:
            donations = [
                {**_resource(donation_id), "relationships": relationship_data(f"x{donation_id}")}
                for donation_id in donation_ids
            ]
            # The last donation has no child, as a donation with no refund has `"data": null`.
            donations[-1]["relationships"] = {}
            included = [
                {**_resource(f"x{donation_id}", amount_cents=100), "type": resource_type}
                for donation_id in donation_ids[:-1]
            ]
            included.append({**_resource("f1", name="General"), "type": "Fund"})
            return ScriptedResponse(
                json={"data": donations, "included": included, "meta": {"total_count": 101, "count": len(donations)}}
            )

        result = _driver().run(schema, [page([str(i) for i in range(100)]), page(["100"])])

        assert result.raised is None
        assert result.paths == ["/giving/v2/donations", "/giving/v2/donations"]
        assert result.params("include") == [include, include]
        assert result.params("offset") == ["0", "100"]
        assert len(result.rows) == 99
        assert result.rows[0] == {"id": "x0", "donation_id": "0", "amount_cents": 100}
        assert result.committed_states == [PlanningCenterResumeConfig(next_offset=100)]


class TestPlanItemsChainedFanOut:
    def test_fetches_items_per_plan_with_both_parent_ids_on_each_row(self) -> None:
        item = {
            **_resource("i1", title="Welcome", item_type="header", sequence=1),
            "relationships": {"plan": {"data": {"type": "Plan", "id": "p1"}}, "song": {"data": None}},
        }
        result = _driver().run(
            "plan_items",
            route(
                {
                    "/services/v2/service_types": [_page([_resource("st1"), _resource("st2")], 2)],
                    "/services/v2/service_types/st1/plans": [_page([_resource("p1")], 1)],
                    "/services/v2/service_types/st2/plans": [_page([_resource("p2")], 1)],
                    "/services/v2/service_types/st1/plans/p1/items": [_page([item], 1)],
                    # A plan deleted after its plans page was read.
                    "/services/v2/service_types/st2/plans/p2/items": [
                        ScriptedResponse(status=404, json={"errors": [{"status": "404"}]})
                    ],
                }
            ),
        )

        assert result.raised is None
        assert sorted(result.paths) == [
            "/services/v2/service_types",
            "/services/v2/service_types/st1/plans",
            "/services/v2/service_types/st1/plans/p1/items",
            "/services/v2/service_types/st2/plans",
            "/services/v2/service_types/st2/plans/p2/items",
        ]
        assert {request.headers["x-pco-api-version"] for request in result.requests} == {"2018-11-01"}
        assert result.rows == [
            {
                "id": "i1",
                "service_type_id": "st1",
                "plan_id": "p1",
                "title": "Welcome",
                "item_type": "header",
                "sequence": 1,
                "song_id": None,
            }
        ]
        assert result.response is not None
        assert result.response.supports_resume is False


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
