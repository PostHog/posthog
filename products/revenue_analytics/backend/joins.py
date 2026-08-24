from products.data_tools.backend.models.join import DataWarehouseJoin
from products.warehouse_sources.backend.facade.api import list_revenue_source_settings
from products.warehouse_sources.backend.facade.contracts import RevenueSourceSettings
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


def get_customer_revenue_view_name(table_prefix: str | None = None) -> str:
    prefix = table_prefix.strip("_") if table_prefix else ""
    if prefix:
        return f"stripe.{prefix}.customer_revenue_view"
    return "stripe.customer_revenue_view"


def get_stripe_sources_for_team(team_id: int) -> list[RevenueSourceSettings]:
    return list_revenue_source_settings(
        team_id,
        source_types=[ExternalDataSourceType.STRIPE],
    )


def _enabled_stripe_sources(team_id: int) -> list[RevenueSourceSettings]:
    return [source for source in get_stripe_sources_for_team(team_id) if source.enabled]


def ensure_person_join_for_team(team_id: int) -> None:
    for source in _enabled_stripe_sources(team_id):
        ensure_person_join(team_id, source.prefix)


def ensure_person_join(team_id: int, table_prefix: str | None = None) -> None:
    prefix = table_prefix or ""
    DataWarehouseJoin.create_if_missing(
        team_id=team_id,
        deleted=False,
        source_table_name=get_customer_revenue_view_name(prefix),
        source_table_key="JSONExtractString(metadata, 'posthog_person_distinct_id')",
        joining_table_name="persons",
        joining_table_key="pdi.distinct_id",
        field_name="persons",
    )


def remove_person_join_for_team(team_id: int) -> None:
    for source in _enabled_stripe_sources(team_id):
        remove_person_join(team_id, source.prefix)


def remove_person_join(team_id: int, table_prefix: str | None = None) -> None:
    prefix = table_prefix or ""
    for join in DataWarehouseJoin.objects.filter(
        team_id=team_id,
        source_table_name=get_customer_revenue_view_name(prefix),
        joining_table_name="persons",
        field_name="persons",
        deleted=False,
    ):
        join.soft_delete()
