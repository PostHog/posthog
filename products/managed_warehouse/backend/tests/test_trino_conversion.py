import re
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import psycopg
from dagster import build_op_context
from parameterized import parameterized
from psycopg import sql

from posthog.dags.events_backfill_to_duckling import (
    EVENTS_TABLE_DDL,
    EVENTS_TRINO_COLUMN_TYPES,
    PERSONS_TABLE_DDL,
    PERSONS_TRINO_COLUMN_TYPES,
    DucklingTarget,
)

from products.managed_warehouse.dags.groups_backfill import GROUPS_COLUMN_TYPES, GROUPS_TRINO_COLUMN_TYPES
from products.managed_warehouse.dags.trino_conversion import (
    DucklingTrinoConversionConfig,
    duckling_trino_conversion,
    plan_table_conversion,
)

TARGET = DucklingTarget(
    team_id=2,
    organization_id="org-1",
    bucket="bkt",
    bucket_region="us-east-1",
    events_table="events_team_2",
    persons_table="persons_team_2",
)


def _ddl_types(ddl: str) -> dict[str, str]:
    columns = re.findall(r"^\s+(\w+) (\w+),?$", ddl, re.MULTILINE)
    return {name: "TIMESTAMP WITH TIME ZONE" if kind == "TIMESTAMPTZ" else kind for name, kind in columns}


EVENTS_TYPES = _ddl_types(EVENTS_TABLE_DDL)
PERSONS_TYPES = _ddl_types(PERSONS_TABLE_DDL)
CONVERTED_GROUPS_TYPES = {**GROUPS_COLUMN_TYPES, "group_type_index": "SMALLINT"}


class _FakeConnection:
    def __init__(self, tables: dict[str, dict[str, str]]) -> None:
        self.tables = tables
        self.alters: list[tuple[str, str, str]] = []

    def execute(self, query: str | sql.Composable) -> Any:
        statement = query.as_string() if isinstance(query, sql.Composable) else query
        if statement.startswith("DESCRIBE"):
            table = statement.split(".")[-1].strip('"')
            if table not in self.tables:
                raise psycopg.errors.UndefinedTable(table)
            return MagicMock(fetchall=lambda: list(self.tables[table].items()))
        match = re.fullmatch(
            r'ALTER TABLE "\w+"\."posthog"\."(\w+)" ALTER COLUMN "(\w+)" SET DATA TYPE (.+)', statement
        )
        assert match is not None, statement
        table, column, column_type = match.groups()
        self.alters.append((table, column, column_type))
        self.tables[table][column] = column_type
        return MagicMock()


class _FakeSession:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def run(self, what: str, op: Any) -> Any:
        return op(self.connection)

    def close(self) -> None:
        pass


@parameterized.expand(
    [
        (
            "duckgres_groups_widen_the_index",
            "groups",
            GROUPS_COLUMN_TYPES,
            GROUPS_TRINO_COLUMN_TYPES,
            False,
            {"group_type_index": "SMALLINT"},
            {},
        ),
        (
            "duckgres_persons_need_a_rebuild",
            "persons",
            PERSONS_TYPES,
            PERSONS_TRINO_COLUMN_TYPES,
            False,
            {},
            {"person_version": "UBIGINT"},
        ),
        ("duckgres_events_match", "events", EVENTS_TYPES, EVENTS_TRINO_COLUMN_TYPES, False, {}, {}),
        ("converted_groups_need_nothing", "groups", CONVERTED_GROUPS_TYPES, GROUPS_TRINO_COLUMN_TYPES, False, {}, {}),
        (
            "missing_column_needs_a_rebuild",
            "groups",
            {"team_id": "BIGINT"},
            GROUPS_TRINO_COLUMN_TYPES,
            False,
            {},
            {
                "group_type_index": "missing",
                "group_key": "missing",
                "group_properties": "missing",
                "created_at": "missing",
                "_timestamp": "missing",
                "_inserted_at": "missing",
            },
        ),
        ("missing_table", "groups", None, GROUPS_TRINO_COLUMN_TYPES, True, {}, {}),
    ]
)
def test_plan_splits_columns_into_widen_and_rebuild(_name, table, actual, expected, missing, widen, rebuild) -> None:
    plan = plan_table_conversion(table, actual, expected)

    assert (plan.missing, dict(plan.widen), dict(plan.rebuild)) == (missing, widen, rebuild)


def test_plan_refuses_a_trino_type_without_a_duckdb_mapping() -> None:
    with pytest.raises(ValueError, match="no DuckDB type"):
        plan_table_conversion("t", {"c": "BIGINT"}, {"c": "decimal(20,0)"})


@parameterized.expand([("dry_run", True, 0), ("real_run", False, 1)])
def test_conversion_widens_only_what_the_plan_names_and_only_once(_name, dry_run, expected_alters) -> None:
    connection = _FakeConnection(
        {
            "events_team_2": dict(EVENTS_TYPES),
            "persons_team_2": dict(PERSONS_TYPES),
            "groups_team_2": dict(GROUPS_COLUMN_TYPES),
        }
    )
    config = DucklingTrinoConversionConfig(team_id=2, dry_run=dry_run)

    with (
        patch("products.managed_warehouse.dags.trino_conversion._resolve_duckling_target", return_value=TARGET),
        patch("products.managed_warehouse.dags.trino_conversion.resolve_groups_table", return_value="groups_team_2"),
        patch(
            "products.managed_warehouse.dags.trino_conversion._DuckgresSession", return_value=_FakeSession(connection)
        ),
    ):
        duckling_trino_conversion(build_op_context(), config)
        duckling_trino_conversion(build_op_context(), config)

    assert connection.alters == [("groups_team_2", "group_type_index", "SMALLINT")] * expected_alters
    assert connection.tables["persons_team_2"] == PERSONS_TYPES
