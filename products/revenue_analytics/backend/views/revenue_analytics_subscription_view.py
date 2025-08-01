from .revenue_analytics_base_view import RevenueAnalyticsBaseView
from typing import cast
from posthog.hogql import ast
from posthog.models.team.team import Team
from posthog.schema import DatabaseSchemaManagedViewTableKind
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.temporal.data_imports.sources.stripe.constants import (
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
)
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    StringDatabaseField,
    FieldOrTable,
)

SOURCE_VIEW_SUFFIX = "subscription_revenue_view"

FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "source_label": StringDatabaseField(name="source_label"),
    "plan_id": StringDatabaseField(name="plan_id"),
    "product_id": StringDatabaseField(name="product_id"),
    "customer_id": StringDatabaseField(name="customer_id"),
    "status": StringDatabaseField(name="status"),
    "started_at": DateTimeDatabaseField(name="started_at"),
    "ended_at": DateTimeDatabaseField(name="ended_at"),
    "current_period_start": DateTimeDatabaseField(name="current_period_start"),
    "current_period_end": DateTimeDatabaseField(name="current_period_end"),
    "metadata": StringDatabaseField(name="metadata"),
}


def extract_string(json_field: str, key: str) -> ast.Expr:
    return ast.Call(
        name="JSONExtractString",
        args=[ast.Field(chain=[json_field]), ast.Constant(value=key)],
    )


class RevenueAnalyticsSubscriptionView(RevenueAnalyticsBaseView):
    @classmethod
    def get_database_schema_table_kind(cls) -> DatabaseSchemaManagedViewTableKind:
        return DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_SUBSCRIPTION

    # No subscription views for events, we only have that for schema sources
    @classmethod
    def for_events(cls, _team: "Team") -> list["RevenueAnalyticsBaseView"]:
        return []

    @classmethod
    def for_schema_source(cls, source: ExternalDataSource) -> list["RevenueAnalyticsBaseView"]:
        # Currently only works for stripe sources
        if not source.source_type == ExternalDataSource.Type.STRIPE:
            return []

        # Get all schemas for the source, avoid calling `filter` and do the filtering on Python-land
        # to avoid n+1 queries
        schemas = source.schemas.all()
        subscription_schema = next(
            (schema for schema in schemas if schema.name == STRIPE_SUBSCRIPTION_RESOURCE_NAME), None
        )
        if subscription_schema is None:
            return []

        subscription_schema = cast(ExternalDataSchema, subscription_schema)
        if subscription_schema.table is None:
            return []

        table = cast(DataWarehouseTable, subscription_schema.table)
        prefix = RevenueAnalyticsBaseView.get_view_prefix_for_source(source)

        # Even though we need a string query for the view,
        # using an ast allows us to comment what each field means, and
        # avoid manual interpolation of constants, leaving that to the HogQL printer
        #
        # These are all pretty basic, they're simply here to allow future extensions
        # once we start adding fields from sources other than Stripe
        query = ast.SelectQuery(
            select=[
                ast.Alias(alias="id", expr=ast.Field(chain=["id"])),
                ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
                ast.Alias(alias="plan_id", expr=extract_string("plan", "id")),
                ast.Alias(alias="product_id", expr=extract_string("plan", "product")),
                ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
                ast.Alias(alias="status", expr=ast.Field(chain=["status"])),
                ast.Alias(alias="started_at", expr=ast.Field(chain=["created_at"])),
                ast.Alias(alias="ended_at", expr=ast.Field(chain=["ended_at"])),
                ast.Alias(alias="current_period_start", expr=ast.Field(chain=["current_period_start"])),
                ast.Alias(alias="current_period_end", expr=ast.Field(chain=["current_period_end"])),
                ast.Alias(alias="metadata", expr=ast.Field(chain=["metadata"])),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[table.name])),
        )

        return [
            RevenueAnalyticsSubscriptionView(
                id=str(table.id),
                name=RevenueAnalyticsBaseView.get_view_name_for_source(source, SOURCE_VIEW_SUFFIX),
                prefix=prefix,
                query=query.to_hogql(),
                fields=FIELDS,
                source_id=str(source.id),
            )
        ]
