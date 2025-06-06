from .revenue_analytics_base_view import RevenueAnalyticsBaseView
from typing import cast
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.models.team.team import Team
from posthog.schema import DatabaseSchemaManagedViewTableKind
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.temporal.data_imports.pipelines.stripe.constants import (
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
)
from posthog.hogql.database.models import DateTimeDatabaseField, StringDatabaseField, FieldOrTable

SOURCE_VIEW_SUFFIX = "customer_revenue_view"

FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "source_label": StringDatabaseField(name="source_label"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "name": StringDatabaseField(name="name"),
    "email": StringDatabaseField(name="email"),
    "phone": StringDatabaseField(name="phone"),
    "cohort": StringDatabaseField(name="cohort"),
}


class RevenueAnalyticsCustomerView(RevenueAnalyticsBaseView):
    @classmethod
    def get_database_schema_table_kind(cls) -> DatabaseSchemaManagedViewTableKind:
        return DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER

    # No customer views for events, we only have that for schema sources
    @classmethod
    def for_events(cls, team: "Team") -> list["RevenueAnalyticsBaseView"]:
        return []

    @classmethod
    def for_schema_source(cls, source: ExternalDataSource) -> list["RevenueAnalyticsBaseView"]:
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

        invoice_schema = next((schema for schema in schemas if schema.name == STRIPE_INVOICE_RESOURCE_NAME), None)
        invoice_table = None
        if invoice_schema is not None:
            invoice_schema = cast(ExternalDataSchema, invoice_schema)
            invoice_table = invoice_schema.table
            if invoice_table is not None:
                invoice_table = cast(DataWarehouseTable, invoice_table)

        table = cast(DataWarehouseTable, customer_schema.table)
        prefix = RevenueAnalyticsBaseView.get_view_prefix_for_source(source)

        # Even though we need a string query for the view,
        # using an ast allows us to comment what each field means, and
        # avoid manual interpolation of constants, leaving that to the HogQL printer
        #
        # These are all pretty basic, they're simply here to allow future extensions
        # once we start adding fields from sources other than Stripe
        query = ast.SelectQuery(
            select=[
                ast.Alias(alias="id", expr=ast.Field(chain=["outer", "id"])),
                ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
                ast.Alias(alias="timestamp", expr=ast.Field(chain=["created_at"])),
                ast.Alias(alias="name", expr=ast.Field(chain=["name"])),
                ast.Alias(alias="email", expr=ast.Field(chain=["email"])),
                ast.Alias(alias="phone", expr=ast.Field(chain=["phone"])),
                ast.Alias(alias="cohort", expr=ast.Field(chain=["cohort_readable"])),
            ],
            select_from=ast.JoinExpr(
                alias="outer",
                table=ast.Field(chain=[table.name]),
                next_join=ast.JoinExpr(
                    alias="cohort_inner",
                    table=ast.SelectQuery(
                        select=[
                            ast.Field(chain=["customer_id"]),
                            ast.Alias(alias="cohort", expr=parse_expr("toStartOfMonth(min(created_at))")),
                            ast.Alias(alias="cohort_readable", expr=parse_expr("formatDateTime(cohort, '%Y-%m')")),
                        ],
                        select_from=ast.JoinExpr(alias="invoice", table=ast.Field(chain=[invoice_table.name])),
                        group_by=[ast.Field(chain=["customer_id"])],
                    ),
                    join_type="LEFT JOIN",
                    constraint=ast.JoinConstraint(
                        constraint_type="ON",
                        expr=ast.CompareOperation(
                            left=ast.Field(chain=["cohort_inner", "customer_id"]),
                            right=ast.Field(chain=["outer", "id"]),
                            op=ast.CompareOperationOp.Eq,
                        ),
                    ),
                ),
            ),
        )

        # If there's an invoice table we can generate the cohort entry
        # by looking at the first invoice for each customer
        # if invoice_table is not None:
        #     cohort_alias = next((alias for alias in query.select if alias.alias == "cohort"), None)
        #     if cohort_alias is not None:
        #         cohort_alias.expr = ast.Field(chain=["cohort_readable"])
        #         query.select_from.next_join =

        return [
            RevenueAnalyticsCustomerView(
                id=str(table.id),
                name=RevenueAnalyticsBaseView.get_view_name_for_source(source, SOURCE_VIEW_SUFFIX),
                prefix=prefix,
                query=query.to_hogql(),
                fields=FIELDS,
                source_id=str(source.id),
            )
        ]
