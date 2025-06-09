from typing import cast

from posthog.hogql import ast
from posthog.models.team.team import Team
from posthog.schema import DatabaseSchemaManagedViewTableKind
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.hogql.database.models import (
    StringDatabaseField,
    FieldOrTable,
)
from .revenue_analytics_base_view import RevenueAnalyticsBaseView
from posthog.temporal.data_imports.pipelines.stripe.constants import (
    PRODUCT_RESOURCE_NAME as STRIPE_PRODUCT_RESOURCE_NAME,
)

SOURCE_VIEW_SUFFIX = "product_revenue_view"

FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "name": StringDatabaseField(name="name"),
}


class RevenueAnalyticsProductView(RevenueAnalyticsBaseView):
    @staticmethod
    def get_database_schema_table_kind() -> DatabaseSchemaManagedViewTableKind:
        return DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_PRODUCT

    # NOTE: Products are not supported for events
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
        product_schema = next((schema for schema in schemas if schema.name == STRIPE_PRODUCT_RESOURCE_NAME), None)
        if product_schema is None:
            return []

        product_schema = cast(ExternalDataSchema, product_schema)
        if product_schema.table is None:
            return []

        product_table = cast(DataWarehouseTable, product_schema.table)

        # Even though we need a string query for the view,
        # using an ast allows us to comment what each field means, and
        # avoid manual interpolation of constants, leaving that to the HogQL printer
        query = ast.SelectQuery(
            select=[ast.Field(chain=["id"]), ast.Field(chain=["name"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=[product_table.name])),
        )

        return [
            RevenueAnalyticsProductView(
                id=str(product_table.id),
                name=RevenueAnalyticsBaseView.get_view_name_for_source(source, SOURCE_VIEW_SUFFIX),
                prefix=RevenueAnalyticsBaseView.get_view_prefix_for_source(source),
                query=query.to_hogql(),
                fields=FIELDS,
                source_id=str(source.id),
            )
        ]
