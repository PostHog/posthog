from .revenue_analytics_base_view import RevenueAnalyticsBaseView
from typing import cast

from posthog.hogql import ast
from posthog.models.team.team import Team
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.models.external_data_schema import ExternalDataSchema

from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    StringDatabaseField,
    FieldOrTable,
)

STRIPE_DATA_WAREHOUSE_CUSTOMER_IDENTIFIER = "Customer"
SOURCE_VIEW_SUFFIX = "customer_revenue_view"

FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "name": StringDatabaseField(name="name"),
    "email": StringDatabaseField(name="email"),
    "phone": StringDatabaseField(name="phone"),
}


class RevenueAnalyticsCustomerView(RevenueAnalyticsBaseView):
    # No customer views for events, we only have that for schema sources
    @staticmethod
    def for_events(team: "Team") -> list["RevenueAnalyticsCustomerView"]:
        return []

    @staticmethod
    def for_schema_source(source: ExternalDataSource) -> list["RevenueAnalyticsCustomerView"]:
        # Currently only works for stripe sources
        if not source.source_type == ExternalDataSource.Type.STRIPE:
            return []

        charge_schema = source.schemas.all().filter(name=STRIPE_DATA_WAREHOUSE_CUSTOMER_IDENTIFIER).first()
        if charge_schema is None:
            return []

        charge_schema = cast(ExternalDataSchema, charge_schema)
        if charge_schema.table is None:
            return []

        table = cast(DataWarehouseTable, charge_schema.table)

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
