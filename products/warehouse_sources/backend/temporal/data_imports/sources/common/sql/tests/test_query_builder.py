from __future__ import annotations

import datetime

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.identifiers import (
    AnsiIdentifierQuoter,
    BacktickIdentifierQuoter,
    InvalidIdentifierError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    ColumnTypeCategory,
    ValidatedRowFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.query_builder import (
    ParamStyle,
    SelectQueryBuilder,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


class TestSelectAllFullRefresh:
    builder = SelectQueryBuilder(quoter=BacktickIdentifierQuoter())

    def test_builds_unqualified_select_with_backticks(self) -> None:
        result = self.builder.select_all(schema="mydb", table_name="messages")
        assert result.sql == "SELECT * FROM `mydb`.`messages`"
        assert result.params == {}

    def test_extra_hint_is_appended_verbatim(self) -> None:
        result = self.builder.select_all(
            schema="mydb",
            table_name="messages",
            extra_table_hint="FORCE INDEX (`idx_created_at`)",
        )
        assert "FORCE INDEX (`idx_created_at`)" in result.sql
        assert result.sql.startswith("SELECT * FROM `mydb`.`messages` FORCE INDEX")

    def test_injection_in_identifier_raises(self) -> None:
        with pytest.raises(InvalidIdentifierError):
            self.builder.select_all(schema="mydb", table_name="messages; DROP TABLE x")


class TestSelectAllIncremental:
    builder = SelectQueryBuilder(quoter=BacktickIdentifierQuoter())

    def test_pyformat_named_placeholder_is_used_for_value(self) -> None:
        result = self.builder.select_all(
            schema="mydb",
            table_name="messages",
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            incremental_last_value=datetime.datetime(2025, 1, 1),
        )
        assert "%(incremental_value)s" in result.sql
        assert "WHERE `created_at` > %(incremental_value)s" in result.sql
        assert "ORDER BY `created_at` ASC" in result.sql
        assert result.params == {"incremental_value": datetime.datetime(2025, 1, 1)}

    def test_value_never_interpolated_into_sql(self) -> None:
        """SQL-injection guard: the value string must stay in params."""
        result = self.builder.select_all(
            schema="mydb",
            table_name="messages",
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            incremental_last_value="2025'; DROP TABLE x; --",
        )
        assert "DROP TABLE" not in result.sql
        assert result.params == {"incremental_value": "2025'; DROP TABLE x; --"}

    def test_initial_value_used_when_last_value_is_none(self) -> None:
        result = self.builder.select_all(
            schema="mydb",
            table_name="messages",
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.Integer,
            incremental_last_value=None,
        )
        assert isinstance(result.params, dict)
        assert result.params["incremental_value"] == 0

    def test_incremental_field_type_required(self) -> None:
        with pytest.raises(ValueError, match="incremental_field_type is required"):
            self.builder.select_all(
                schema="mydb",
                table_name="messages",
                incremental_field="created_at",
                incremental_field_type=None,
            )

    def test_date_type_uses_inclusive_operator(self) -> None:
        result = self.builder.select_all(
            schema="mydb",
            table_name="messages",
            incremental_field="event_date",
            incremental_field_type=IncrementalFieldType.Date,
            incremental_last_value=datetime.date(2025, 1, 1),
        )
        assert "WHERE `event_date` >= %(incremental_value)s" in result.sql

    def test_order_by_can_be_suppressed(self) -> None:
        result = self.builder.select_all(
            schema="mydb",
            table_name="messages",
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            incremental_last_value=datetime.datetime(2025, 1, 1),
            order_by_incremental=False,
        )
        assert "ORDER BY" not in result.sql


class TestSelectAllEnabledColumns:
    builder = SelectQueryBuilder(quoter=BacktickIdentifierQuoter())

    def test_none_emits_select_star(self) -> None:
        result = self.builder.select_all(schema="db", table_name="t", enabled_columns=None)
        assert result.sql.startswith("SELECT * FROM ")

    def test_subset_projects_and_keeps_pks(self) -> None:
        result = self.builder.select_all(
            schema="db",
            table_name="t",
            enabled_columns=["email"],
            primary_keys=["id"],
        )
        assert result.sql.startswith("SELECT `email`, `id` FROM ")

    def test_subset_keeps_incremental_field(self) -> None:
        result = self.builder.select_all(
            schema="db",
            table_name="t",
            enabled_columns=["email"],
            primary_keys=["id"],
            incremental_field="updated_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            incremental_last_value=datetime.datetime(2025, 1, 1),
        )
        # Order: enabled first, PKs next, then incremental.
        assert result.sql.startswith("SELECT `email`, `id`, `updated_at` FROM ")
        assert "WHERE `updated_at` > %(incremental_value)s" in result.sql

    def test_empty_list_with_no_pk_falls_back_to_star(self) -> None:
        result = self.builder.select_all(schema="db", table_name="t", enabled_columns=[])
        assert result.sql.startswith("SELECT * FROM ")

    def test_empty_list_keeps_pks_and_incremental(self) -> None:
        result = self.builder.select_all(
            schema="db",
            table_name="t",
            enabled_columns=[],
            primary_keys=["id"],
            incremental_field="updated_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            incremental_last_value=datetime.datetime(2025, 1, 1),
        )
        assert result.sql.startswith("SELECT `id`, `updated_at` FROM ")


class TestParamStyles:
    def test_qmark_style_emits_question_mark(self) -> None:
        builder = SelectQueryBuilder(quoter=AnsiIdentifierQuoter(), param_style=ParamStyle.QMARK)
        result = builder.select_all(
            schema="public",
            table_name="users",
            incremental_field="id",
            incremental_field_type=IncrementalFieldType.Integer,
            incremental_last_value=42,
        )
        assert 'WHERE "id" > ?' in result.sql
        assert result.params == [42]

    def test_named_style_uses_colon_prefix(self) -> None:
        builder = SelectQueryBuilder(quoter=AnsiIdentifierQuoter(), param_style=ParamStyle.NAMED)
        result = builder.select_all(
            schema="public",
            table_name="users",
            incremental_field="id",
            incremental_field_type=IncrementalFieldType.Integer,
            incremental_last_value=42,
        )
        assert ":incremental_value" in result.sql
        assert result.params == {"incremental_value": 42}

    def test_numeric_style_uses_positional_number(self) -> None:
        builder = SelectQueryBuilder(quoter=AnsiIdentifierQuoter(), param_style=ParamStyle.NUMERIC)
        result = builder.select_all(
            schema="public",
            table_name="users",
            incremental_field="id",
            incremental_field_type=IncrementalFieldType.Integer,
            incremental_last_value=42,
        )
        assert ":1" in result.sql
        assert result.params == [42]

    def test_empty_params_match_style(self) -> None:
        qmark = SelectQueryBuilder(quoter=AnsiIdentifierQuoter(), param_style=ParamStyle.QMARK)
        named = SelectQueryBuilder(quoter=AnsiIdentifierQuoter(), param_style=ParamStyle.PYFORMAT_NAMED)
        assert qmark.select_all(schema="public", table_name="t").params == []
        assert named.select_all(schema="public", table_name="t").params == {}


class TestSelectAllRowFilters:
    builder = SelectQueryBuilder(quoter=BacktickIdentifierQuoter())

    def _filter(self, column: str, operator: str, value: object) -> ValidatedRowFilter:
        return ValidatedRowFilter(column=column, operator=operator, value=value, category=ColumnTypeCategory.INTEGER)

    def test_single_filter_emits_where_and_param(self) -> None:
        result = self.builder.select_all(
            schema="db",
            table_name="t",
            row_filters=[self._filter("age", ">", 21)],
        )
        assert "WHERE `age` > %(row_filter_0)s" in result.sql
        assert result.params == {"row_filter_0": 21}

    def test_multiple_filters_are_anded(self) -> None:
        result = self.builder.select_all(
            schema="db",
            table_name="t",
            row_filters=[self._filter("age", ">", 21), self._filter("score", "<=", 100)],
        )
        assert "WHERE `age` > %(row_filter_0)s AND `score` <= %(row_filter_1)s" in result.sql
        assert result.params == {"row_filter_0": 21, "row_filter_1": 100}

    def test_filters_compose_with_incremental(self) -> None:
        result = self.builder.select_all(
            schema="db",
            table_name="t",
            incremental_field="updated_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            incremental_last_value=datetime.datetime(2025, 1, 1),
            row_filters=[self._filter("age", ">", 21)],
        )
        # Incremental condition first, then the row filter, both ANDed; ORDER BY still present.
        assert (
            "WHERE `updated_at` > %(incremental_value)s AND `age` > %(row_filter_0)s ORDER BY `updated_at` ASC"
            in result.sql
        )
        assert isinstance(result.params, dict)
        assert result.params["incremental_value"] == datetime.datetime(2025, 1, 1)
        assert result.params["row_filter_0"] == 21

    def test_value_never_interpolated(self) -> None:
        result = self.builder.select_all(
            schema="db",
            table_name="t",
            row_filters=[
                ValidatedRowFilter(
                    column="name", operator="=", value="x'; DROP TABLE y; --", category=ColumnTypeCategory.STRING
                )
            ],
        )
        assert "DROP TABLE" not in result.sql
        assert isinstance(result.params, dict)
        assert result.params["row_filter_0"] == "x'; DROP TABLE y; --"

    def test_positional_style_orders_filters_after_incremental(self) -> None:
        builder = SelectQueryBuilder(quoter=AnsiIdentifierQuoter(), param_style=ParamStyle.NUMERIC)
        result = builder.select_all(
            schema="public",
            table_name="users",
            incremental_field="id",
            incremental_field_type=IncrementalFieldType.Integer,
            incremental_last_value=5,
            row_filters=[self._filter("age", ">", 21)],
        )
        # Incremental value is bound first (:1), row filter second (:2) — order matters for positional params.
        assert result.params == [5, 21]
        assert ":1" in result.sql and ":2" in result.sql

    def test_in_filter_expands_to_one_placeholder_per_value(self) -> None:
        result = self.builder.select_all(
            schema="db",
            table_name="t",
            row_filters=[self._filter("age", "IN", [21, 30, 40])],
        )
        assert "WHERE `age` IN (%(row_filter_0_0)s, %(row_filter_0_1)s, %(row_filter_0_2)s)" in result.sql
        assert result.params == {"row_filter_0_0": 21, "row_filter_0_1": 30, "row_filter_0_2": 40}

    def test_in_filter_positional_order_after_incremental(self) -> None:
        builder = SelectQueryBuilder(quoter=AnsiIdentifierQuoter(), param_style=ParamStyle.NUMERIC)
        result = builder.select_all(
            schema="public",
            table_name="users",
            incremental_field="id",
            incremental_field_type=IncrementalFieldType.Integer,
            incremental_last_value=5,
            row_filters=[self._filter("age", "NOT IN", [21, 30])],
        )
        # Incremental value bound first, then each IN element in order.
        assert result.params == [5, 21, 30]
        assert '"age" NOT IN (:2, :3)' in result.sql

    def test_none_row_filters_no_where(self) -> None:
        result = self.builder.select_all(schema="db", table_name="t", row_filters=None)
        assert "WHERE" not in result.sql

    def test_malicious_column_rejected(self) -> None:
        with pytest.raises(InvalidIdentifierError):
            self.builder.select_all(
                schema="db",
                table_name="t",
                row_filters=[self._filter("age`; DROP TABLE x; --", ">", 21)],
            )
