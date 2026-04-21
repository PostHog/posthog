from django.db.models import QuerySet

from products.data_warehouse.backend.models import ExternalDataSource
from products.data_warehouse.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.types import ExternalDataSourceType


def get_customer_revenue_view_name(table_prefix: str | None = None) -> str:
    prefix = table_prefix.strip("_") if table_prefix else ""
    if prefix:
        return f"stripe.{prefix}.customer_revenue_view"
    return "stripe.customer_revenue_view"


def get_stripe_sources_for_team(team_id: int) -> QuerySet[ExternalDataSource]:
    return ExternalDataSource.objects.filter(
        team_id=team_id,
        source_type=ExternalDataSourceType.STRIPE,
    ).exclude(deleted=True)


def ensure_person_join_for_team(team_id: int) -> None:
    sources = get_stripe_sources_for_team(team_id)
    for source in sources:
        if source.revenue_analytics_config_safe.enabled:
            ensure_person_join(team_id, source.prefix)


def ensure_person_join(team_id: int, table_prefix: str | None = None) -> None:
    prefix = table_prefix or ""
    DataWarehouseJoin.objects.get_or_create(
        team_id=team_id,
        deleted=False,
        source_table_name=get_customer_revenue_view_name(prefix),
        source_table_key="JSONExtractString(metadata, 'posthog_person_distinct_id')",
        joining_table_name="persons",
        joining_table_key="pdi.distinct_id",
        field_name="persons",
    )


def remove_person_join_for_team(team_id: int) -> None:
    sources = get_stripe_sources_for_team(team_id)
    for source in sources:
        if source.revenue_analytics_config_safe.enabled:
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
