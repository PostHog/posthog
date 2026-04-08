from products.data_warehouse.backend.models.join import DataWarehouseJoin


def get_customer_revenue_view_name(table_prefix: str) -> str:
    stripped = table_prefix.strip("_")
    if stripped:
        return f"stripe.{stripped}.customer_revenue_view"
    return "stripe.customer_revenue_view"


def ensure_person_join(team_id: int, table_prefix: str) -> None:
    DataWarehouseJoin.objects.get_or_create(
        team_id=team_id,
        deleted=False,
        source_table_name=get_customer_revenue_view_name(table_prefix),
        source_table_key="JSONExtractString(metadata, 'posthog_person_distinct_id')",
        joining_table_name="persons",
        joining_table_key="pdi.distinct_id",
        field_name="persons",
    )


def remove_person_join(team_id: int, table_prefix: str) -> None:
    for join in DataWarehouseJoin.objects.filter(
        team_id=team_id,
        source_table_name=get_customer_revenue_view_name(table_prefix),
        joining_table_name="persons",
        field_name="persons",
        deleted=False,
    ):
        join.soft_delete()
