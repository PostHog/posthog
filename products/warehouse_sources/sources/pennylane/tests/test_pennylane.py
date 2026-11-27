import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine

from parameterized import parameterized

from products.warehouse_sources.sources.pennylane._config import PennylaneSourceConfig
from products.warehouse_sources.sources.pennylane.pennylane import PennylaneResumeConfig, validate_credentials
from products.warehouse_sources.sources.pennylane.settings import AUTH_ERROR, FORBIDDEN_ERROR, scope_error
from products.warehouse_sources.sources.pennylane.source import PennylaneSource
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
API_PATH = "/api/external/v2"


@pytest.fixture(autouse=True)
def _frozen_clock() -> Iterator[None]:
    with time_machine.travel(NOW, tick=False):
        yield


def _page(items: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"items": items, "has_more": next_cursor is not None, "next_cursor": next_cursor})


def _change(record_id: int, operation: str = "update") -> dict[str, Any]:
    return {
        "id": record_id,
        "operation": operation,
        "processed_at": "2026-06-14T10:00:00.000000Z",
        "updated_at": "2026-06-14T10:00:00.000000Z",
        "created_at": "2026-01-01T00:00:00.000000Z",
    }


def _run(
    schema_name: str,
    script: list[ScriptedResponse] | Callable[[RecordedRequest], ScriptedResponse],
    **inputs: Any,
) -> DriveResult:
    result = SourceDriver(PennylaneSource(), PennylaneSourceConfig(api_key="pl_token")).run(
        schema_name, script, **inputs
    )
    assert result.raised is None, result.raised
    return result


def _id_filter(ids: list[int]) -> str:
    return json.dumps([{"field": "id", "operator": "in", "value": ids}])


class TestFullList:
    @parameterized.expand(
        [
            ("sorted_by_id", "customers", "id"),
            ("no_documented_sort", "category_groups", None),
        ]
    )
    def test_walks_every_page_and_stages_the_next_cursor(
        self, _name: str, schema_name: str, expected_sort: str | None
    ) -> None:
        result = _run(
            schema_name,
            [_page([{"id": 1}, {"id": 2}], next_cursor="c2"), _page([{"id": 3}])],
        )

        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert result.paths == [f"{API_PATH}/{schema_name}"] * 2
        assert result.params("cursor") == [None, "c2"]
        assert result.params("sort") == [expected_sort] * 2
        assert result.params("limit") == ["100", "100"]
        assert result.requests[0].headers["authorization"] == "Bearer pl_token"
        assert result.committed_states == [PennylaneResumeConfig(cursor="c2")]


class TestChangelogIncremental:
    def test_fetches_the_changed_records_and_pages_the_changelog_without_start_date(self) -> None:
        result = _run(
            "customer_invoices",
            [
                _page(
                    [_change(1), _change(2, "insert"), _change(1), _change(3, "delete")],
                    next_cursor="cl2",
                ),
                _page(
                    [{"id": 1, "updated_at": "2026-06-14T10:00:00Z"}, {"id": 2, "updated_at": "2026-06-14T10:00:00Z"}]
                ),
                _page([_change(4, "delete")]),
            ],
            incremental_field="updated_at",
            db_incremental_field_last_value="2026-06-10T08:30:00Z",
        )

        assert [row["id"] for row in result.rows] == [1, 2]
        assert result.paths == [
            f"{API_PATH}/changelogs/customer_invoices",
            f"{API_PATH}/customer_invoices",
            f"{API_PATH}/changelogs/customer_invoices",
        ]
        assert result.params("start_date") == ["2026-06-10T08:20:00Z", None, None]
        assert result.params("cursor") == [None, None, "cl2"]
        assert result.params("filter") == [None, _id_filter([1, 2]), None]
        assert result.committed_states == [PennylaneResumeConfig(cursor="cl2", changelog=True)]

    @parameterized.expand(
        [
            ("first_sync", True, None, "/customers"),
            ("watermark_as_datetime", True, NOW - timedelta(days=3), "/changelogs/customers"),
            ("watermark_past_changelog_retention", True, NOW - timedelta(days=28), "/customers"),
            ("full_refresh_ignores_watermark", False, NOW - timedelta(days=3), "/customers"),
        ]
    )
    def test_reads_the_changelog_only_when_it_covers_the_watermark(
        self, _name: str, incremental: bool, watermark: datetime | None, expected_path: str
    ) -> None:
        result = _run(
            "customers",
            [_page([])],
            incremental_field="updated_at",
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=watermark,
        )

        assert result.paths == [f"{API_PATH}{expected_path}"]


class TestResume:
    @parameterized.expand(
        [
            ("list_cursor", "customers", PennylaneResumeConfig(cursor="c5"), {}, "/customers", "c5", None),
            (
                "changelog_cursor_replaces_start_date",
                "customers",
                PennylaneResumeConfig(cursor="cl5", changelog=True),
                {"incremental_field": "updated_at", "db_incremental_field_last_value": "2026-06-14T00:00:00Z"},
                "/changelogs/customers",
                "cl5",
                None,
            ),
            (
                "list_cursor_is_not_a_changelog_position",
                "customers",
                PennylaneResumeConfig(cursor="c5"),
                {"incremental_field": "updated_at", "db_incremental_field_last_value": "2026-06-14T00:00:00Z"},
                "/changelogs/customers",
                None,
                "2026-06-13T23:50:00Z",
            ),
        ]
    )
    def test_first_request_continues_from_the_saved_position(
        self,
        _name: str,
        schema_name: str,
        resume_state: PennylaneResumeConfig,
        inputs: dict[str, Any],
        expected_path: str,
        expected_cursor: str | None,
        expected_start_date: str | None,
    ) -> None:
        result = _run(schema_name, [_page([])], resume_state=resume_state, **inputs)

        assert result.paths == [f"{API_PATH}{expected_path}"]
        assert result.params("cursor") == [expected_cursor]
        assert result.params("start_date") == [expected_start_date]


_FANOUT_TABLES = [
    ("customer_invoice_lines", "customer_invoices", "invoice_lines", "customer_invoice_id"),
    ("customer_invoice_payments", "customer_invoices", "payments", "customer_invoice_id"),
    ("supplier_invoice_lines", "supplier_invoices", "invoice_lines", "supplier_invoice_id"),
    ("customer_contacts", "customers", "contacts", "customer_id"),
]


def _child_path(parent: str, parent_id: int, child: str) -> str:
    return f"{API_PATH}/{parent}/{parent_id}/{child}"


class TestFanOut:
    @parameterized.expand(_FANOUT_TABLES)
    def test_walks_every_parent_and_child_page_and_skips_a_deleted_parent(
        self, schema_name: str, parent: str, child: str, parent_id_column: str
    ) -> None:
        result = _run(
            schema_name,
            route(
                {
                    f"{API_PATH}/{parent}": [_page([{"id": 1}, {"id": 2}], next_cursor="p2"), _page([{"id": 3}])],
                    _child_path(parent, 1, child): [_page([{"id": 10}], next_cursor="c2"), _page([{"id": 11}])],
                    _child_path(parent, 2, child): [ScriptedResponse(status=404, json={"error": "not found"})],
                    _child_path(parent, 3, child): [_page([{"id": 10}])],
                }
            ),
        )

        assert [(row[parent_id_column], row["id"]) for row in result.rows] == [(1, 10), (1, 11), (3, 10)]
        assert all(f"_{parent}_id" not in row for row in result.rows)
        assert result.response is not None
        assert result.response.primary_keys == [parent_id_column, "id"]
        parent_requests = [r for r in result.requests if r.path == f"{API_PATH}/{parent}"]
        assert [r.param("cursor") for r in parent_requests] == [None, "p2"]
        assert [r.param("cursor") for r in result.requests if r.path == _child_path(parent, 1, child)] == [None, "c2"]
        assert {(r.param("sort"), r.param("limit")) for r in result.requests} == {("id", "100")}

    def test_resume_restarts_the_parent_listing_near_the_saved_page_and_skips_finished_parents(self) -> None:
        parent_pages = [
            _page([{"id": 1}], next_cursor="p2"),
            _page([{"id": 2}], next_cursor="p3"),
            _page([{"id": 3}, {"id": 4}]),
        ]
        children = {_child_path("customers", n, "contacts"): [_page([{"id": n * 10}])] for n in range(1, 5)}
        first = _run("customer_contacts", route({f"{API_PATH}/customers": parent_pages, **children}))
        after_customer_3 = next(
            state
            for state in first.saved_states
            if state.fanout_state and "/customers/3/contacts" in state.fanout_state["completed"]
        )

        result = _run(
            "customer_contacts",
            route(
                {
                    f"{API_PATH}/customers": parent_pages[1:],
                    _child_path("customers", 4, "contacts"): [_page([{"id": 40}])],
                }
            ),
            resume_state=after_customer_3,
        )

        assert [r.param("cursor") for r in result.requests if r.path == f"{API_PATH}/customers"] == ["p2", "p3"]
        assert [row["id"] for row in result.rows] == [40]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid_token", None, 200, (True, None), "/me"),
            ("rejected_token", None, 401, (False, AUTH_ERROR), "/me"),
            ("token_refused", None, 403, (False, FORBIDDEN_ERROR), "/me"),
            ("table_readable", "transactions", 200, (True, None), "/transactions"),
            ("table_missing_scope", "transactions", 403, (False, scope_error("transactions")), "/transactions"),
            (
                "child_table_reads_its_parent",
                "customer_invoice_lines",
                403,
                (False, scope_error("customer_invoice_lines")),
                "/customer_invoices",
            ),
        ]
    )
    def test_maps_the_probe_status(
        self,
        _name: str,
        schema_name: str | None,
        status: int,
        expected: tuple[bool, str | None],
        expected_path: str,
    ) -> None:
        body = {"status": status, "error": "denied"} if status != 200 else {"items": []}
        with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
            assert validate_credentials("pl_token", schema_name) == expected

        assert [request.path for request in network.requests_log] == [f"{API_PATH}{expected_path}"]
