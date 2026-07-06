from parameterized import parameterized

from products.warehouse_sources.backend.models.external_table_definitions import get_hogql_column_name_mapping


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
