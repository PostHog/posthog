import json
from contextlib import nullcontext
from decimal import Decimal

import pytest
from unittest.mock import MagicMock, patch

from posthog.hogql.errors import ExposedHogQLError

from posthog.models import Team, User

from products.managed_warehouse.backend.facade.contracts import (
    ControlPlaneUpstreamError,
    StorageOverview,
    StorageTableUsage,
)
from products.managed_warehouse.backend.logic.query_estimate import estimate_managed_trino_query
from products.managed_warehouse.backend.query_execution import ManagedTrinoSql

GIB = 1024**3
MODULE = "products.managed_warehouse.backend.logic.query_estimate"


def _table(schema: str, table: str, *, constrained: bool) -> dict:
    return {
        "table": {"catalog": "org_example", "schemaTable": {"schema": schema, "table": table}},
        "constraint": {
            "none": False,
            "columnConstraints": (
                [
                    {
                        "columnName": "day",
                        "type": "date",
                        "domain": {
                            "nullsAllowed": False,
                            "ranges": [
                                {
                                    "low": {"value": "2026-01-01", "bound": "EXACTLY"},
                                    "high": {"value": "2026-01-31", "bound": "EXACTLY"},
                                }
                            ],
                        },
                    }
                ]
                if constrained
                else []
            ),
        },
        "estimate": {
            "outputRowCount": "NaN",
            "outputSizeInBytes": "NaN",
            "cpuCost": "NaN",
            "maxMemory": "NaN",
            "networkCost": "NaN",
        },
    }


def _plan(*tables: dict) -> list[tuple[str]]:
    return [
        (
            json.dumps(
                {
                    "inputTableColumnInfos": list(tables),
                    "estimate": {
                        "outputRowCount": "NaN",
                        "outputSizeInBytes": "NaN",
                        "cpuCost": "NaN",
                        "maxMemory": "NaN",
                        "networkCost": "NaN",
                    },
                }
            ),
        )
    ]


def _storage(**sizes: int) -> StorageOverview:
    return StorageOverview(
        tables=tuple(
            StorageTableUsage(
                schema="sales",
                table=name,
                data_bytes=size,
                delete_bytes=0,
                file_count=1,
                row_count=1,
                last_modified_at=None,
            )
            for name, size in sizes.items()
        ),
        total_bytes=sum(sizes.values()),
        pending_deletion_files=0,
        read_at=None,
        maintenance=None,
    )


def _run(
    plan: list[tuple[str]],
    storage: StorageOverview,
    cap: int | None = None,
    *,
    raw: bool = True,
    prepared: ManagedTrinoSql | None = None,
    storage_error: Exception | None = None,
) -> tuple:
    cursor = MagicMock()
    cursor.fetchall.return_value = plan
    connection = MagicMock()
    connect = MagicMock(return_value=nullcontext(connection))
    team = Team(id=7, organization_id="00000000-0000-0000-0000-000000000001")
    user = User(id=9)
    with (
        patch(f"{MODULE}.validate_managed_trino_query"),
        patch(f"{MODULE}.UserAccessControl"),
        patch(
            f"{MODULE}.prepare_managed_trino_sql",
            return_value=prepared or ManagedTrinoSql(sql="SELECT 1", values=None, hogql=None),
        ),
        patch(f"{MODULE}.connect_managed_warehouse_trino", connect),
        patch(f"{MODULE}.bounded_trino_cursor", return_value=nullcontext((cursor, MagicMock()))),
        patch(f"{MODULE}.get_storage_overview", return_value=storage, side_effect=storage_error),
        patch(f"{MODULE}.get_max_scan_bytes_per_query", return_value=cap),
    ):
        result = estimate_managed_trino_query(team, user, query="SELECT 1", send_raw_query=raw)
    return result, cursor, connect


@pytest.mark.parametrize(
    "tables, storage, cap, upper, complete, exceeds, warnings",
    [
        ([("orders", True)], {"orders": 20 * GIB}, None, 20 * GIB, True, False, []),
        ([("orders", False)], {"orders": 20 * GIB}, None, 20 * GIB, True, False, ["no_filter_on_large_table"]),
        ([("orders", False)], {"orders": GIB}, None, GIB, True, False, []),
        (
            [("orders", False), ("customers", True)],
            {"orders": 20 * GIB, "customers": 5 * GIB},
            10 * GIB,
            25 * GIB,
            True,
            True,
            ["no_filter_on_large_table", "exceeds_cap"],
        ),
        ([("orders", True), ("missing", True)], {"orders": 2 * GIB}, None, 2 * GIB, False, False, ["size_unknown"]),
        ([("orders", True)], {"orders": 10 * GIB}, 10 * GIB, 10 * GIB, True, False, []),
    ],
)
def test_upper_bound_filters_cap_and_completeness(
    tables: list[tuple[str, bool]],
    storage: dict[str, int],
    cap: int | None,
    upper: int,
    complete: bool,
    exceeds: bool,
    warnings: list[str],
) -> None:
    result, _, _ = _run(_plan(*[_table("sales", name, constrained=c) for name, c in tables]), _storage(**storage), cap)
    assert result.upper_bound_bytes == upper
    assert result.complete is complete
    assert result.exceeds_cap is exceeds
    assert list(result.warnings) == warnings
    assert result.cap_bytes == cap
    assert result.estimated_cost_usd == Decimal(upper) / Decimal(1024**4) * Decimal("2.50")


@pytest.mark.parametrize(
    "rows",
    [[], [("not json",)], [(json.dumps({"inputTableColumnInfos": [{"table": {}}]}),)], [(json.dumps([1]),)]],
)
def test_a_malformed_explain_result_is_an_exposed_error(rows: list) -> None:
    with pytest.raises(ExposedHogQLError, match="Couldn't estimate this query"):
        _run(rows, _storage())


def test_a_storage_failure_after_explain_leaves_sizes_unknown() -> None:
    result, _, _ = _run(
        _plan(_table("sales", "orders", constrained=False)),
        _storage(),
        storage_error=ControlPlaneUpstreamError("body"),
    )
    assert [t.size_bytes for t in result.tables] == [None]
    assert result.complete is False
    assert result.upper_bound_bytes is None
    assert result.estimated_cost_usd is None
    assert list(result.warnings) == ["size_unknown"]


def test_variables_and_filters_reach_the_compile_step() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = _plan(_table("sales", "orders", constrained=True))
    team = Team(id=7, organization_id="00000000-0000-0000-0000-000000000001")
    with (
        patch(f"{MODULE}.validate_managed_trino_query"),
        patch(f"{MODULE}.UserAccessControl"),
        patch(
            f"{MODULE}.prepare_managed_trino_sql", return_value=ManagedTrinoSql(sql="SELECT 1", values=None, hogql=None)
        ) as prepare,
        patch(f"{MODULE}.connect_managed_warehouse_trino", return_value=nullcontext(MagicMock())),
        patch(f"{MODULE}.bounded_trino_cursor", return_value=nullcontext((cursor, MagicMock()))),
        patch(f"{MODULE}.get_storage_overview", return_value=_storage(orders=GIB)),
        patch(f"{MODULE}.get_max_scan_bytes_per_query", return_value=None),
    ):
        estimate_managed_trino_query(
            team,
            User(id=9),
            query="SELECT {variables.region}",
            send_raw_query=False,
            variables={"v1": {"variableId": "v1", "code_name": "region", "value": "eu"}},
            filters={"dateRange": {"date_from": "-7d"}},
        )
        query = prepare.call_args.args[0]
        assert query.variables["v1"].code_name == "region"
        assert query.filters.dateRange.date_from == "-7d"
        with pytest.raises(ExposedHogQLError, match="not valid"):
            estimate_managed_trino_query(
                team, User(id=9), query="SELECT 1", send_raw_query=False, variables={"v1": "bad"}
            )


def test_no_sized_table_leaves_the_bound_and_cost_unknown() -> None:
    result, _, _ = _run(_plan(_table("sales", "missing", constrained=True)), _storage(orders=GIB), cap=GIB)
    assert result.upper_bound_bytes is None
    assert result.estimated_cost_usd is None
    assert result.complete is False
    assert result.exceeds_cap is False


def test_explain_runs_as_the_editor_principal_from_the_console_source() -> None:
    _, cursor, connect = _run(_plan(_table("sales", "orders", constrained=True)), _storage(orders=GIB))
    assert connect.call_args.kwargs["source"] == "posthog-console"
    assert connect.call_args.kwargs["principal"] == "posthog:sql-editor:team:7:user:9"
    cursor.execute.assert_called_once_with("EXPLAIN (TYPE IO, FORMAT JSON) SELECT 1")


def test_compiled_sql_is_explained_with_bound_values() -> None:
    prepared = ManagedTrinoSql(
        sql='SELECT * FROM "sales"."orders" WHERE a = %(value_0)s', values={"value_0": "x"}, hogql="SELECT 1"
    )
    _, cursor, _ = _run(
        _plan(_table("sales", "orders", constrained=True)), _storage(orders=GIB), raw=False, prepared=prepared
    )
    cursor.execute.assert_called_once_with(
        'EXPLAIN (TYPE IO, FORMAT JSON) SELECT * FROM "sales"."orders" WHERE a = ?', ["x"]
    )


def test_a_trino_failure_becomes_an_exposed_error() -> None:
    cursor = MagicMock()
    cursor.execute.side_effect = RuntimeError("Table 'org_example.sales.nope' does not exist")
    team = Team(id=7, organization_id="00000000-0000-0000-0000-000000000001")
    with (
        patch(f"{MODULE}.validate_managed_trino_query"),
        patch(f"{MODULE}.UserAccessControl"),
        patch(
            f"{MODULE}.prepare_managed_trino_sql", return_value=ManagedTrinoSql(sql="SELECT 1", values=None, hogql=None)
        ),
        patch(f"{MODULE}.connect_managed_warehouse_trino", return_value=nullcontext(MagicMock())),
        patch(f"{MODULE}.bounded_trino_cursor", return_value=nullcontext((cursor, MagicMock()))),
    ):
        with pytest.raises(ExposedHogQLError, match="does not exist"):
            estimate_managed_trino_query(team, User(id=9), query="SELECT 1", send_raw_query=True)
