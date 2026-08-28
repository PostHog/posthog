from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable

from products.warehouse_sources.backend.models.table import DataWarehouseTable


def test_hogql_definition_exposes_recorded_column_order_to_duckdb() -> None:
    table = DataWarehouseTable(
        name="headerless_orders",
        format="CSV",
        team_id=1,
        url_pattern="s3://bucket/orders.csv",
        columns={
            "amount": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
            "order_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
        },
        column_order=["order_id", "amount"],
    )

    definition = table.hogql_definition()

    assert isinstance(definition, HogQLDataWarehouseTable)
    assert definition.column_names == ("order_id", "amount")
    assert definition.clickhouse_column_types == ("String", "String")
