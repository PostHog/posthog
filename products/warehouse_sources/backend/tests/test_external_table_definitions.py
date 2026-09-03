from parameterized import parameterized

from posthog.hogql import ast

from products.warehouse_sources.backend.models.external_table_definitions import (
    _referenced_keys,
    external_tables,
    get_hogql_column_name_mapping,
    resolve_external_table_fields,
)


def _plain_columns(table: str) -> set[str]:
    return {field.name for field in external_tables[table].values() if not isinstance(field, ast.ExpressionField)}


def _reads(field: object) -> set[str]:
    return _referenced_keys(field) if isinstance(field, ast.ExpressionField) else set()


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

        assert relocated_into in _reads(resolve_external_table_fields(table, columns)[key])
        # Without the new column the field must stop referencing it. The s3() structure is built
        # from the synced columns, so a field reaching outside it fails every query on the table.
        assert relocated_into not in _reads(resolve_external_table_fields(table, columns - {relocated_into})[key])

    def test_drops_a_curated_field_whose_column_is_missing(self) -> None:
        resolved = resolve_external_table_fields("stripe_invoice", _plain_columns("stripe_invoice") - {"parent"})

        assert "parent" not in resolved
        assert "subscription_id" in resolved

    def test_keeps_every_field_when_all_columns_are_present(self) -> None:
        columns = _plain_columns("stripe_invoice")

        assert set(resolve_external_table_fields("stripe_invoice", columns)) == set(external_tables["stripe_invoice"])

    def test_unknown_table_has_no_curated_fields(self) -> None:
        assert resolve_external_table_fields("some_postgres_table", []) is None
