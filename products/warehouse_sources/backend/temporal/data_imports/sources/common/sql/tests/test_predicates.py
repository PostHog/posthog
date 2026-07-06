from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.identifiers import (
    AnsiIdentifierQuoter,
    BacktickIdentifierQuoter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    _BOOLEAN_TYPES,
    _DATE_TYPES,
    _INTEGER_TYPES,
    _NUMERIC_TYPES,
    _STRING_TYPES,
    _TIMESTAMP_TYPES,
    ColumnTypeCategory,
    RowFilterValidationError,
    ValidatedRowFilter,
    classify_column_type,
    normalize_operator,
    render_named_conditions,
    render_positional_conditions,
    validate_and_coerce_row_filters,
)


def _metadata(columns: list[tuple[str, str]]) -> dict:
    return {"columns": [{"name": name, "data_type": data_type} for name, data_type in columns]}


class TestNormalizeOperator:
    @pytest.mark.parametrize("operator", [">", ">=", "<", "<=", "=", "!="])
    def test_canonical_operators_pass_through(self, operator: str) -> None:
        assert normalize_operator(operator) == operator

    def test_aliases_are_normalized(self) -> None:
        assert normalize_operator("==") == "="
        assert normalize_operator("<>") == "!="

    def test_whitespace_is_stripped(self) -> None:
        assert normalize_operator("  >=  ") == ">="

    @pytest.mark.parametrize(
        "operator,expected",
        [
            ("IN", "IN"),
            ("in", "IN"),
            ("In", "IN"),
            ("  in  ", "IN"),
            ("NOT IN", "NOT IN"),
            ("not in", "NOT IN"),
            ("Not  In", "NOT IN"),  # collapsed internal whitespace
        ],
    )
    def test_in_operators_are_normalized(self, operator: str, expected: str) -> None:
        assert normalize_operator(operator) == expected

    @pytest.mark.parametrize("operator", ["LIKE", "=;DROP", "", "OR 1=1", ">>", "NOTIN", "IN;DROP"])
    def test_disallowed_operators_raise(self, operator: str) -> None:
        with pytest.raises(RowFilterValidationError):
            normalize_operator(operator)

    @pytest.mark.parametrize("operator", [1, None, [">"], {">": 1}])
    def test_non_string_operators_raise(self, operator: object) -> None:
        with pytest.raises(RowFilterValidationError):
            normalize_operator(operator)


class TestClassifyColumnType:
    @pytest.mark.parametrize(
        "data_type,expected",
        [
            ("integer", ColumnTypeCategory.INTEGER),
            ("bigint", ColumnTypeCategory.INTEGER),
            ("int8", ColumnTypeCategory.INTEGER),
            ("smallint", ColumnTypeCategory.INTEGER),
            ("UInt64", ColumnTypeCategory.INTEGER),
            ("numeric(10,2)", ColumnTypeCategory.NUMERIC),
            ("decimal", ColumnTypeCategory.NUMERIC),
            ("double precision", ColumnTypeCategory.NUMERIC),
            ("Float64", ColumnTypeCategory.NUMERIC),
            ("NUMBER", ColumnTypeCategory.NUMERIC),
            ("varchar(255)", ColumnTypeCategory.STRING),
            ("text", ColumnTypeCategory.STRING),
            ("uuid", ColumnTypeCategory.STRING),
            ("FixedString(8)", ColumnTypeCategory.STRING),
            # json / jsonb are unfilterable: a text-bound comparison fails at sync time.
            ("json", ColumnTypeCategory.UNKNOWN),
            ("jsonb", ColumnTypeCategory.UNKNOWN),
            ("boolean", ColumnTypeCategory.BOOLEAN),
            ("bool", ColumnTypeCategory.BOOLEAN),
            ("bit", ColumnTypeCategory.BOOLEAN),
            ("date", ColumnTypeCategory.DATE),
            ("Date32", ColumnTypeCategory.DATE),
            ("timestamp", ColumnTypeCategory.TIMESTAMP),
            ("timestamp with time zone", ColumnTypeCategory.TIMESTAMP),
            ("timestamp(6)", ColumnTypeCategory.TIMESTAMP),
            ("datetime", ColumnTypeCategory.TIMESTAMP),
            ("DateTime64(3, 'UTC')", ColumnTypeCategory.TIMESTAMP),
            ("smalldatetime", ColumnTypeCategory.TIMESTAMP),
        ],
    )
    def test_classification(self, data_type: str, expected: ColumnTypeCategory) -> None:
        assert classify_column_type(data_type) == expected

    def test_case_insensitive(self) -> None:
        assert classify_column_type("INTEGER") == ColumnTypeCategory.INTEGER
        assert classify_column_type("VarChar(10)") == ColumnTypeCategory.STRING


class TestTypeVocabularyParity:
    """The classifier's type sets are duplicated in the frontend (rowFilterUtils.ts). Assert the
    two stay in sync so a column type can't be filterable on one side and not the other."""

    # parents[9] is the repo root from this file's depth
    # (products/warehouse_sources/backend/temporal/data_imports/sources/common/sql/tests/).
    _TS_PATH = (
        Path(__file__).resolve().parents[9]
        / "products/data_warehouse/frontend/scenes/SourceScene/tabs/rowFilterUtils.ts"
    )

    def _ts_set(self, name: str) -> set[str]:
        source = self._TS_PATH.read_text()
        match = re.search(rf"const {name} = new Set\(\[(.*?)\]\)", source, re.DOTALL)
        assert match, f"{name} not found in rowFilterUtils.ts"
        body = re.sub(r"//[^\n]*", "", match.group(1))  # drop line comments first
        return set(re.findall(r"'([^']*)'", body))

    @pytest.mark.parametrize(
        "ts_name,py_set",
        [
            ("INTEGER_TYPES", _INTEGER_TYPES),
            ("NUMERIC_TYPES", _NUMERIC_TYPES),
            ("STRING_TYPES", _STRING_TYPES),
            ("BOOLEAN_TYPES", _BOOLEAN_TYPES),
            ("DATE_TYPES", _DATE_TYPES),
            ("TIMESTAMP_TYPES", _TIMESTAMP_TYPES),
        ],
    )
    def test_python_and_typescript_type_sets_match(self, ts_name: str, py_set: set[str]) -> None:
        assert self._ts_set(ts_name) == py_set

    def test_nullable_wrapper_is_stripped(self) -> None:
        assert classify_column_type("Nullable(Int64)") == ColumnTypeCategory.INTEGER
        assert classify_column_type("Nullable(DateTime64(3))") == ColumnTypeCategory.TIMESTAMP
        assert classify_column_type("LowCardinality(Nullable(String))") == ColumnTypeCategory.STRING

    @pytest.mark.parametrize("data_type", ["", "   ", "geometry", "bytea", "array", "hstore", None, 123])
    def test_unknown_types(self, data_type: object) -> None:
        assert classify_column_type(data_type) == ColumnTypeCategory.UNKNOWN


class TestValidateAndCoerce:
    def test_none_returns_empty(self) -> None:
        assert validate_and_coerce_row_filters(None, _metadata([("id", "integer")])) == []

    def test_empty_list_returns_empty(self) -> None:
        assert validate_and_coerce_row_filters([], _metadata([("id", "integer")])) == []

    def test_non_list_raises(self) -> None:
        with pytest.raises(RowFilterValidationError, match="must be a list"):
            validate_and_coerce_row_filters({"column": "id"}, _metadata([("id", "integer")]))

    def test_too_many_filters_raises(self) -> None:
        metadata = _metadata([("id", "integer")])
        filters = [{"column": "id", "operator": ">", "value": 1} for _ in range(21)]
        with pytest.raises(RowFilterValidationError, match="Too many row filters"):
            validate_and_coerce_row_filters(filters, metadata)

    def test_unknown_column_raises(self) -> None:
        with pytest.raises(RowFilterValidationError, match="Unknown column"):
            validate_and_coerce_row_filters(
                [{"column": "nope", "operator": ">", "value": 1}], _metadata([("id", "integer")])
            )

    def test_missing_column_raises(self) -> None:
        with pytest.raises(RowFilterValidationError, match="missing a column"):
            validate_and_coerce_row_filters([{"operator": ">", "value": 1}], _metadata([("id", "integer")]))

    def test_missing_value_raises(self) -> None:
        with pytest.raises(RowFilterValidationError, match="missing a value"):
            validate_and_coerce_row_filters([{"column": "id", "operator": ">"}], _metadata([("id", "integer")]))

    def test_unsupported_column_type_raises(self) -> None:
        with pytest.raises(RowFilterValidationError, match="not supported for filtering"):
            validate_and_coerce_row_filters(
                [{"column": "geo", "operator": "=", "value": "x"}], _metadata([("geo", "geometry")])
            )

    def test_filter_at_index_must_be_object(self) -> None:
        with pytest.raises(RowFilterValidationError, match="must be an object"):
            validate_and_coerce_row_filters(["not a dict"], _metadata([("id", "integer")]))

    def test_integer_coercion(self) -> None:
        result = validate_and_coerce_row_filters(
            [{"column": "id", "operator": ">", "value": "42"}], _metadata([("id", "integer")])
        )
        assert result == [ValidatedRowFilter(column="id", operator=">", value=42, category=ColumnTypeCategory.INTEGER)]

    @pytest.mark.parametrize("value", [True, False, "3.5", "abc", 3.5])
    def test_integer_rejects_bad_values(self, value: object) -> None:
        with pytest.raises(RowFilterValidationError):
            validate_and_coerce_row_filters(
                [{"column": "id", "operator": ">", "value": value}], _metadata([("id", "integer")])
            )

    def test_numeric_coercion_from_string(self) -> None:
        result = validate_and_coerce_row_filters(
            [{"column": "amount", "operator": ">=", "value": "3.14"}], _metadata([("amount", "numeric")])
        )
        assert result[0].value == Decimal("3.14")
        assert result[0].category == ColumnTypeCategory.NUMERIC

    def test_numeric_rejects_non_number(self) -> None:
        with pytest.raises(RowFilterValidationError):
            validate_and_coerce_row_filters(
                [{"column": "amount", "operator": ">", "value": "not-a-number"}], _metadata([("amount", "numeric")])
            )

    def test_string_coercion(self) -> None:
        result = validate_and_coerce_row_filters(
            [{"column": "name", "operator": "=", "value": "alice"}], _metadata([("name", "varchar(50)")])
        )
        assert result[0].value == "alice"

    @pytest.mark.parametrize("value", [1, 1.5, True, None])
    def test_string_rejects_non_string(self, value: object) -> None:
        with pytest.raises(RowFilterValidationError):
            validate_and_coerce_row_filters(
                [{"column": "name", "operator": "=", "value": value}], _metadata([("name", "text")])
            )

    @pytest.mark.parametrize(
        "value,expected",
        [(True, True), (False, False), ("true", True), ("false", False), (1, True), (0, False)],
    )
    def test_boolean_coercion(self, value: object, expected: bool) -> None:
        # Integers 0/1 are accepted (valid JSON encodings of booleans a direct API caller may send).
        result = validate_and_coerce_row_filters(
            [{"column": "active", "operator": "=", "value": value}], _metadata([("active", "boolean")])
        )
        assert result[0].value is expected

    @pytest.mark.parametrize("value", ["yes", "1", 2, -1, None])
    def test_boolean_rejects_bad_values(self, value: object) -> None:
        with pytest.raises(RowFilterValidationError):
            validate_and_coerce_row_filters(
                [{"column": "active", "operator": "=", "value": value}], _metadata([("active", "boolean")])
            )

    def test_date_coercion(self) -> None:
        result = validate_and_coerce_row_filters(
            [{"column": "d", "operator": ">", "value": "2026-01-01"}], _metadata([("d", "date")])
        )
        assert result[0].value == date(2026, 1, 1)

    @pytest.mark.parametrize("value", ["2026-13-01", "not-a-date", "01/01/2026", 20260101])
    def test_date_rejects_bad_values(self, value: object) -> None:
        with pytest.raises(RowFilterValidationError):
            validate_and_coerce_row_filters(
                [{"column": "d", "operator": ">", "value": value}], _metadata([("d", "date")])
            )

    def test_timestamp_coercion_iso(self) -> None:
        result = validate_and_coerce_row_filters(
            [{"column": "ts", "operator": ">", "value": "2026-01-01T12:30:00"}], _metadata([("ts", "timestamp")])
        )
        assert result[0].value == datetime(2026, 1, 1, 12, 30, 0)

    def test_timestamp_accepts_trailing_z(self) -> None:
        result = validate_and_coerce_row_filters(
            [{"column": "ts", "operator": ">", "value": "2026-01-01T12:30:00Z"}], _metadata([("ts", "timestamp")])
        )
        assert result[0].value.year == 2026

    def test_timestamp_accepts_plain_date(self) -> None:
        result = validate_and_coerce_row_filters(
            [{"column": "ts", "operator": ">", "value": "2026-01-01"}], _metadata([("ts", "timestamp")])
        )
        assert result[0].value == datetime(2026, 1, 1, 0, 0, 0)

    def test_multiple_filters(self) -> None:
        result = validate_and_coerce_row_filters(
            [
                {"column": "id", "operator": ">", "value": 10},
                {"column": "name", "operator": "!=", "value": "bob"},
            ],
            _metadata([("id", "integer"), ("name", "text")]),
        )
        assert len(result) == 2
        assert result[0].operator == ">"
        assert result[1].operator == "!="

    def test_alias_operator_is_normalized_in_result(self) -> None:
        result = validate_and_coerce_row_filters(
            [{"column": "id", "operator": "==", "value": 1}], _metadata([("id", "integer")])
        )
        assert result[0].operator == "="

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1,2,3", [1, 2, 3]),
            ("1, 2, 3", [1, 2, 3]),
            ("  1 ,  2 ,3 ", [1, 2, 3]),
            ("42", [42]),
        ],
    )
    def test_in_integer_list_coercion(self, raw: str, expected: list[int]) -> None:
        result = validate_and_coerce_row_filters(
            [{"column": "id", "operator": "IN", "value": raw}], _metadata([("id", "integer")])
        )
        assert result[0].operator == "IN"
        assert result[0].value == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("'abc','cde'", ["abc", "cde"]),
            ("'abc', 'cde'", ["abc", "cde"]),
            ("abc,cde", ["abc", "cde"]),  # quotes are optional when there's no embedded comma
            ("'a,b','c'", ["a,b", "c"]),  # commas inside quotes are preserved
            ("'o''brien'", ["o'brien"]),  # doubled quote escapes
        ],
    )
    def test_in_string_list_coercion(self, raw: str, expected: list[str]) -> None:
        result = validate_and_coerce_row_filters(
            [{"column": "name", "operator": "IN", "value": raw}], _metadata([("name", "text")])
        )
        assert result[0].value == expected

    def test_not_in_operator(self) -> None:
        result = validate_and_coerce_row_filters(
            [{"column": "id", "operator": "not in", "value": "1,2"}], _metadata([("id", "integer")])
        )
        assert result[0].operator == "NOT IN"
        assert result[0].value == [1, 2]

    def test_in_accepts_structured_list(self) -> None:
        result = validate_and_coerce_row_filters(
            [{"column": "id", "operator": "IN", "value": [1, "2", 3]}], _metadata([("id", "integer")])
        )
        assert result[0].value == [1, 2, 3]

    def test_in_empty_list_raises(self) -> None:
        with pytest.raises(RowFilterValidationError, match="at least one value"):
            validate_and_coerce_row_filters(
                [{"column": "id", "operator": "IN", "value": ""}], _metadata([("id", "integer")])
            )

    def test_in_blank_element_raises(self) -> None:
        with pytest.raises(RowFilterValidationError, match="empty value"):
            validate_and_coerce_row_filters(
                [{"column": "id", "operator": "IN", "value": "1,,2"}], _metadata([("id", "integer")])
            )

    def test_in_bad_element_type_raises(self) -> None:
        with pytest.raises(RowFilterValidationError):
            validate_and_coerce_row_filters(
                [{"column": "id", "operator": "IN", "value": "1,abc,3"}], _metadata([("id", "integer")])
            )

    def test_in_unterminated_quote_raises(self) -> None:
        with pytest.raises(RowFilterValidationError, match="Unterminated quote"):
            validate_and_coerce_row_filters(
                [{"column": "name", "operator": "IN", "value": "'abc"}], _metadata([("name", "text")])
            )

    def test_in_too_many_values_raises(self) -> None:
        raw = ",".join(str(n) for n in range(1001))
        with pytest.raises(RowFilterValidationError, match="Too many values"):
            validate_and_coerce_row_filters(
                [{"column": "id", "operator": "IN", "value": raw}], _metadata([("id", "integer")])
            )

    def test_no_metadata_columns_skips_existence_check(self) -> None:
        # With no discovered columns we can't classify the type, so it fails the type rail
        # rather than the column-existence rail.
        with pytest.raises(RowFilterValidationError, match="not supported for filtering"):
            validate_and_coerce_row_filters([{"column": "id", "operator": ">", "value": 1}], None)


class TestRenderNamedConditions:
    quoter = BacktickIdentifierQuoter()

    def test_renders_placeholders_and_params(self) -> None:
        filters = [
            ValidatedRowFilter(column="id", operator=">", value=10, category=ColumnTypeCategory.INTEGER),
            ValidatedRowFilter(column="name", operator="!=", value="bob", category=ColumnTypeCategory.STRING),
        ]
        conditions, params = render_named_conditions(filters, self.quoter)
        assert conditions == ["`id` > %(row_filter_0)s", "`name` != %(row_filter_1)s"]
        assert params == {"row_filter_0": 10, "row_filter_1": "bob"}

    def test_value_never_in_condition_text(self) -> None:
        filters = [
            ValidatedRowFilter(
                column="name", operator="=", value="x'; DROP TABLE y; --", category=ColumnTypeCategory.STRING
            )
        ]
        conditions, params = render_named_conditions(filters, self.quoter)
        assert "DROP TABLE" not in conditions[0]
        assert params["row_filter_0"] == "x'; DROP TABLE y; --"

    def test_custom_prefix(self) -> None:
        filters = [ValidatedRowFilter(column="id", operator=">", value=1, category=ColumnTypeCategory.INTEGER)]
        conditions, params = render_named_conditions(filters, self.quoter, prefix="rf")
        assert conditions == ["`id` > %(rf_0)s"]
        assert "rf_0" in params

    def test_in_expands_to_one_placeholder_per_value(self) -> None:
        filters = [
            ValidatedRowFilter(column="id", operator="IN", value=[1, 2, 3], category=ColumnTypeCategory.INTEGER),
        ]
        conditions, params = render_named_conditions(filters, self.quoter)
        assert conditions == ["`id` IN (%(row_filter_0_0)s, %(row_filter_0_1)s, %(row_filter_0_2)s)"]
        assert params == {"row_filter_0_0": 1, "row_filter_0_1": 2, "row_filter_0_2": 3}

    def test_not_in_renders_operator(self) -> None:
        filters = [
            ValidatedRowFilter(column="name", operator="NOT IN", value=["a", "b"], category=ColumnTypeCategory.STRING),
        ]
        conditions, params = render_named_conditions(filters, self.quoter)
        assert conditions == ["`name` NOT IN (%(row_filter_0_0)s, %(row_filter_0_1)s)"]
        assert params == {"row_filter_0_0": "a", "row_filter_0_1": "b"}


class TestRenderPositionalConditions:
    quoter = AnsiIdentifierQuoter()

    def test_renders_in_order(self) -> None:
        filters = [
            ValidatedRowFilter(column="id", operator=">", value=10, category=ColumnTypeCategory.INTEGER),
            ValidatedRowFilter(column="name", operator="=", value="bob", category=ColumnTypeCategory.STRING),
        ]
        conditions, values = render_positional_conditions(filters, self.quoter)
        assert conditions == ['"id" > %s', '"name" = %s']
        assert values == [10, "bob"]

    def test_value_never_in_condition_text(self) -> None:
        filters = [
            ValidatedRowFilter(
                column="name", operator="=", value="'; DROP TABLE y; --", category=ColumnTypeCategory.STRING
            )
        ]
        conditions, values = render_positional_conditions(filters, self.quoter)
        assert "DROP TABLE" not in conditions[0]
        assert values == ["'; DROP TABLE y; --"]

    def test_in_expands_in_order(self) -> None:
        filters = [
            ValidatedRowFilter(column="id", operator="IN", value=[10, 20], category=ColumnTypeCategory.INTEGER),
            ValidatedRowFilter(column="name", operator="=", value="bob", category=ColumnTypeCategory.STRING),
        ]
        conditions, values = render_positional_conditions(filters, self.quoter)
        assert conditions == ['"id" IN (%s, %s)', '"name" = %s']
        assert values == [10, 20, "bob"]

    def test_in_injection_value_stays_a_bound_param(self) -> None:
        # A malicious element survives as data only — it's one bound value, never SQL.
        filters = [
            ValidatedRowFilter(
                column="name",
                operator="IN",
                value=["ok", "'); DROP SCHEMA s CASCADE; --"],
                category=ColumnTypeCategory.STRING,
            )
        ]
        conditions, values = render_positional_conditions(filters, self.quoter)
        assert conditions == ['"name" IN (%s, %s)']
        assert "DROP SCHEMA" not in conditions[0]
        assert values == ["ok", "'); DROP SCHEMA s CASCADE; --"]


class TestInjectionGuards:
    """A malicious column name never reaches SQL: it's rejected by the quoter or the column allowlist."""

    def test_malicious_column_rejected_by_allowlist(self) -> None:
        with pytest.raises(RowFilterValidationError, match="Unknown column"):
            validate_and_coerce_row_filters(
                [{"column": "id; DROP TABLE x", "operator": ">", "value": 1}],
                _metadata([("id", "integer")]),
            )

    def test_malicious_column_rejected_by_quoter_at_render(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.identifiers import (
            InvalidIdentifierError,
        )

        # Even if a bad identifier somehow reaches render, the quoter rejects it.
        filters = [
            ValidatedRowFilter(
                column='id"; DROP TABLE x; --', operator=">", value=1, category=ColumnTypeCategory.INTEGER
            )
        ]
        with pytest.raises(InvalidIdentifierError):
            render_named_conditions(filters, BacktickIdentifierQuoter())
