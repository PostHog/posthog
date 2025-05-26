from .revenue_analytics_base_view import RevenueAnalyticsBaseView
from typing import cast

from posthog.hogql import ast
from posthog.models.team.team import Team
from posthog.schema import DatabaseSchemaManagedViewTableKind
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.temporal.data_imports.pipelines.stripe.constants import (
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
)

from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    StringDatabaseField,
    FieldOrTable,
)

SOURCE_VIEW_SUFFIX = "customer_revenue_view"

FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "name": StringDatabaseField(name="name"),
    "email": StringDatabaseField(name="email"),
    "phone": StringDatabaseField(name="phone"),
}


class RevenueAnalyticsCustomerView(RevenueAnalyticsBaseView):
    @staticmethod
    def get_database_schema_table_kind() -> DatabaseSchemaManagedViewTableKind:
        return DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER

    # No customer views for events, we only have that for schema sources
    @staticmethod
    def for_events(team: "Team") -> list["RevenueAnalyticsBaseView"]:
        return []

    @staticmethod
    def for_schema_source(source: ExternalDataSource) -> list["RevenueAnalyticsBaseView"]:
        # Currently only works for stripe sources
        if not source.source_type == ExternalDataSource.Type.STRIPE:
            return []

        # Get all schemas for the source, avoid calling `filter` and do the filtering on Python-land
        # to avoid n+1 queries
        schemas = source.schemas.all()
        customer_schema = next((schema for schema in schemas if schema.name == STRIPE_CUSTOMER_RESOURCE_NAME), None)
        if customer_schema is None:
            return []

        customer_schema = cast(ExternalDataSchema, customer_schema)
        if customer_schema.table is None:
            return []

        table = cast(DataWarehouseTable, customer_schema.table)

        # Even though we need a string query for the view,
        # using an ast allows us to comment what each field means, and
        # avoid manual interpolation of constants, leaving that to the HogQL printer
        #
        # These are all pretty basic, they're simply here to allow future extensions
        # once we start adding fields from sources other than Stripe
        query = ast.SelectQuery(
            select=[
                ast.Alias(alias="id", expr=ast.Field(chain=["id"])),
                ast.Alias(alias="timestamp", expr=ast.Field(chain=["created_at"])),
                ast.Alias(alias="name", expr=ast.Field(chain=["name"])),
                ast.Alias(alias="email", expr=ast.Field(chain=["email"])),
                ast.Alias(alias="phone", expr=ast.Field(chain=["phone"])),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[table.name])),
        )

        return [
            RevenueAnalyticsCustomerView(
                id=str(table.id),
                name=RevenueAnalyticsBaseView.get_view_name_for_source(source, SOURCE_VIEW_SUFFIX),
                query=query.to_hogql(),
                fields=FIELDS,
                source_id=str(source.id),
            )
        ]
