from collections.abc import Collection

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.functions.mapping import find_hogql_function
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

from products.warehouse_sources.backend.models.external_table_definitions import (
    _MOVED_COLUMN_FIELDS,
    _referenced_keys,
    external_tables,
    get_hogql_column_name_mapping,
    resolve_external_table_fields,
)


def _plain_columns(table: str) -> set[str]:
    return {field.name for field in external_tables[table].values() if not isinstance(field, ast.ExpressionField)}


def _reads(field: object) -> set[str]:
    return _referenced_keys(field) if isinstance(field, ast.ExpressionField) else set()


def _resolve(table: str, columns: Collection[str]) -> dict[str, DatabaseField]:
    fields = resolve_external_table_fields(table, columns)
    assert fields is not None
    return fields


class TestGetHogqlColumnNameMapping:
    @parameterized.expand(
        [
            # Direct renames (`StringDatabaseField(name="customer")` exposed as `customer_id`).
            ("stripe_charge", "customer", "customer_id"),
            ("stripe_charge", "invoice", "invoice_id"),
            ("stripe_charge", "payment_intent", "payment_intent_id"),
            ("stripe_charge", "balance_transaction", "balance_transaction_id"),
            # Expression renames: raw column feeds a hidden `__created` field wrapped by a visible
            # `created_at` ExpressionField — the mapping must resolve through the expression.
            ("stripe_charge", "created", "created_at"),
            ("stripe_invoice", "period_start", "period_start_at"),
            ("stripe_invoice", "period_end", "period_end_at"),
            ("stripe_creditnote", "voided_at", "voided_at"),
            ("stripe_subscription", "latest_invoice", "latest_invoice_id"),
        ]
    )
    def test_maps_raw_column_to_hogql_visible_name(self, table: str, raw: str, expected: str) -> None:
        assert get_hogql_column_name_mapping(table)[raw] == expected

    def test_non_renamed_columns_map_to_themselves(self) -> None:
        mapping = get_hogql_column_name_mapping("stripe_charge")
        assert mapping["amount"] == "amount"
        assert mapping["currency"] == "currency"

    def test_hidden_alias_field_is_never_a_target(self) -> None:
        # Raw `created` must resolve to the visible `created_at`, never the hidden `__created` alias.
        assert "__created" not in get_hogql_column_name_mapping("stripe_charge").values()

    def test_unknown_table_returns_empty_mapping(self) -> None:
        # Arbitrary SQL sources have no curated definition — raw names are exposed unchanged.
        assert get_hogql_column_name_mapping("some_postgres_table") == {}


class TestResolveExternalTableFields:
    @parameterized.expand(
        [
            ("stripe_invoice", "subscription_id", "parent"),
            ("stripe_subscription", "current_period_start", "items"),
            ("stripe_subscription", "current_period_end", "items"),
            ("stripe_invoiceitem", "unit_amount", "pricing"),
            ("stripe_invoiceitem", "unit_amount_decimal", "pricing"),
        ]
    )
    def test_reads_the_relocated_column_only_when_the_table_has_it(
        self, table: str, key: str, relocated_into: str
    ) -> None:
        columns = _plain_columns(table)

        assert relocated_into in _reads(_resolve(table, columns)[key])
        # Without the new column the field must stop referencing it. The s3() structure is built
        # from the synced columns, so a field reaching outside it fails every query on the table.
        assert relocated_into not in _reads(_resolve(table, columns - {relocated_into})[key])

    def test_drops_a_curated_field_whose_column_is_missing(self) -> None:
        resolved = _resolve("stripe_invoice", _plain_columns("stripe_invoice") - {"parent"})

        assert "parent" not in resolved
        assert "subscription_id" in resolved

    def test_keeps_every_field_when_all_columns_are_present(self) -> None:
        columns = _plain_columns("stripe_invoice")

        assert set(_resolve("stripe_invoice", columns)) == set(external_tables["stripe_invoice"])

    def test_unknown_table_has_no_curated_fields(self) -> None:
        assert resolve_external_table_fields("some_postgres_table", []) is None


class _CallNameCollector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()

    def visit_call(self, node: ast.Call) -> None:
        self.names.add(node.name)
        for arg in node.args:
            self.visit(arg)
        for param in node.params or []:
            self.visit(param)


class TestCuratedExpressionsCallRealFunctions:
    def test_every_expression_uses_a_function_hogql_knows(self) -> None:
        # A ClickHouse-only or misspelled name builds fine in Python and only fails when someone
        # queries the table, so every curated and relocated expression is checked here instead.
        unknown: set[str] = set()
        tables: list[dict[str, object]] = [dict(fields) for fields in external_tables.values()]
        tables += [dict(fields) for fields in _MOVED_COLUMN_FIELDS.values()]

        for fields in tables:
            for field in fields.values():
                if not isinstance(field, ast.ExpressionField):
                    continue
                collector = _CallNameCollector()
                collector.visit(field.expr)
                unknown |= {name for name in collector.names if find_hogql_function(name) is None}

        assert unknown == set()


class _SubstituteColumns(CloningVisitor):
    """Replaces the column references in a curated expression with literal values."""

    def __init__(self, values: dict[str, object]) -> None:
        super().__init__()
        self._values = values

    def visit_field(self, node: ast.Field) -> ast.Expr:
        if len(node.chain) == 1 and node.chain[0] in self._values:
            return ast.Constant(value=self._values[node.chain[0]])
        return super().visit_field(node)


def _evaluate(table: str, key: str, columns: dict[str, object], team) -> object:
    field = _resolve(table, _plain_columns(table))[key]
    assert isinstance(field, ast.ExpressionField)
    query = ast.SelectQuery(select=[_SubstituteColumns(columns).visit(field.expr)])
    return execute_hogql_query(query, team).results[0][0]


_PERIOD = 1743159813


class TestRelocatedFieldsResolveTheSameValue(ClickhouseTestMixin, BaseTest):
    # The resolver tests above only compare column names, so a wrong JSON path, a mishandled empty
    # list or a broken numeric conversion would still pass them. These run the real expression.
    @parameterized.expand(
        [
            ("legacy", {"__subscription": "sub_x", "parent": None}, "sub_x"),
            (
                "relocated",
                {"__subscription": None, "parent": '{"subscription_details":{"subscription":"sub_x"}}'},
                "sub_x",
            ),
            ("neither", {"__subscription": None, "parent": None}, None),
        ]
    )
    def test_invoice_subscription_id(self, _name, columns, expected) -> None:
        assert _evaluate("stripe_invoice", "subscription_id", columns, self.team) == expected

    @parameterized.expand(
        [
            ("legacy wins", {"__paid": False, "status": "paid"}, False),
            ("relocated", {"__paid": None, "status": "paid"}, True),
            ("relocated unpaid", {"__paid": None, "status": "open"}, False),
        ]
    )
    def test_invoice_paid(self, _name, columns, expected) -> None:
        assert _evaluate("stripe_invoice", "paid", columns, self.team) == expected

    @parameterized.expand(
        [
            ("legacy", {"__current_period_start": _PERIOD, "items": None}),
            (
                "relocated",
                {"__current_period_start": None, "items": f'{{"data":[{{"current_period_start":{_PERIOD}}}]}}'},
            ),
        ]
    )
    def test_subscription_period_start(self, _name, columns) -> None:
        # Both shapes describe the same instant, so they have to render identically.
        assert _evaluate("stripe_subscription", "current_period_start", columns, self.team) == _evaluate(
            "stripe_subscription", "current_period_start", {"__current_period_start": _PERIOD, "items": None}, self.team
        )

    def test_subscription_period_start_without_any_item(self) -> None:
        # An empty item list must read as nothing rather than as the epoch.
        assert (
            _evaluate(
                "stripe_subscription",
                "current_period_start",
                {"__current_period_start": None, "items": '{"data":[]}'},
                self.team,
            )
            is None
        )

    @parameterized.expand(
        [
            ("legacy", {"__unit_amount": 1500, "pricing": None}, 1500),
            ("relocated", {"__unit_amount": None, "pricing": '{"unit_amount_decimal":"1500"}'}, 1500),
            ("neither", {"__unit_amount": None, "pricing": None}, None),
        ]
    )
    def test_invoice_item_unit_amount(self, _name, columns, expected) -> None:
        assert _evaluate("stripe_invoiceitem", "unit_amount", columns, self.team) == expected

    @parameterized.expand(
        [
            ("legacy", {"__unit_amount_decimal": "1500", "pricing": None}, "1500"),
            ("relocated", {"__unit_amount_decimal": None, "pricing": '{"unit_amount_decimal":"1500"}'}, "1500"),
        ]
    )
    def test_invoice_item_unit_amount_decimal(self, _name, columns, expected) -> None:
        assert _evaluate("stripe_invoiceitem", "unit_amount_decimal", columns, self.team) == expected
