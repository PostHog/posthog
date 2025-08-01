from .revenue_analytics_base_view import RevenueAnalyticsBaseView
from typing import cast
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.models.team.team import Team
from posthog.schema import DatabaseSchemaManagedViewTableKind
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.temporal.data_imports.sources.stripe.constants import (
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
)
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    StringDatabaseField,
    FieldOrTable,
    StringJSONDatabaseField,
)
from .revenue_analytics_base_view import events_expr_for_team

SOURCE_VIEW_SUFFIX = "customer_revenue_view"
EVENTS_VIEW_SUFFIX = "customer_events_revenue_view"


def get_cohort_expr(field: str) -> ast.Expr:
    return parse_expr(f"formatDateTime(toStartOfMonth({field}), '%Y-%m')")


FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "source_label": StringDatabaseField(name="source_label"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "name": StringDatabaseField(name="name"),
    "email": StringDatabaseField(name="email"),
    "phone": StringDatabaseField(name="phone"),
    "address": StringJSONDatabaseField(name="address"),
    "metadata": StringJSONDatabaseField(name="metadata"),
    "country": StringDatabaseField(name="country"),
    "cohort": StringDatabaseField(name="cohort"),
    "initial_coupon": StringDatabaseField(name="initial_coupon"),
    "initial_coupon_id": StringDatabaseField(name="initial_coupon_id"),
}


class RevenueAnalyticsCustomerView(RevenueAnalyticsBaseView):
    @classmethod
    def get_database_schema_table_kind(cls) -> DatabaseSchemaManagedViewTableKind:
        return DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER

    @classmethod
    def for_events(cls, team: "Team") -> list["RevenueAnalyticsBaseView"]:
        if len(team.revenue_analytics_config.events) == 0:
            return []

        revenue_config = team.revenue_analytics_config

        queries: list[tuple[str, str, ast.SelectQuery]] = []
        for event in revenue_config.events:
            prefix = RevenueAnalyticsBaseView.get_view_prefix_for_event(event.eventName)

            events_query = ast.SelectQuery(
                distinct=True,
                select=[ast.Alias(alias="person_id", expr=ast.Field(chain=["events", "person", "id"]))],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                where=events_expr_for_team(team),
            )

            query = ast.SelectQuery(
                select=[
                    ast.Alias(alias="id", expr=ast.Call(name="toString", args=[ast.Field(chain=["id"])])),
                    ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
                    ast.Alias(alias="timestamp", expr=ast.Field(chain=["created_at"])),
                    ast.Alias(alias="name", expr=ast.Field(chain=["properties", "name"])),
                    ast.Alias(alias="email", expr=ast.Field(chain=["properties", "email"])),
                    ast.Alias(alias="phone", expr=ast.Field(chain=["properties", "phone"])),
                    ast.Alias(alias="address", expr=ast.Field(chain=["properties", "address"])),
                    ast.Alias(alias="metadata", expr=ast.Field(chain=["properties", "metadata"])),
                    ast.Alias(alias="country", expr=ast.Field(chain=["properties", "$geoip_country_name"])),
                    ast.Alias(alias="cohort", expr=get_cohort_expr("created_at")),
                    ast.Alias(alias="initial_coupon", expr=ast.Constant(value=None)),
                    ast.Alias(alias="initial_coupon_id", expr=ast.Constant(value=None)),
                ],
                select_from=ast.JoinExpr(
                    table=ast.Field(chain=["persons"]),
                    alias="persons",
                    next_join=ast.JoinExpr(
                        table=events_query,
                        alias="events",
                        join_type="INNER JOIN",
                        constraint=ast.JoinConstraint(
                            constraint_type="ON",
                            expr=ast.CompareOperation(
                                left=ast.Field(chain=["id"]),
                                right=ast.Field(chain=["person_id"]),
                                op=ast.CompareOperationOp.Eq,
                            ),
                        ),
                    ),
                ),
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["created_at"]), order="DESC")],
            )

            queries.append((event.eventName, prefix, query))

        return [
            RevenueAnalyticsCustomerView(
                id=RevenueAnalyticsBaseView.get_view_name_for_event(event_name, EVENTS_VIEW_SUFFIX),
                name=RevenueAnalyticsBaseView.get_view_name_for_event(event_name, EVENTS_VIEW_SUFFIX),
                prefix=prefix,
                query=query.to_hogql(),
                fields=FIELDS,
            )
            for event_name, prefix, query in queries
        ]

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
                ast.Alias(alias="address", expr=ast.Field(chain=["address"])),
                ast.Alias(alias="metadata", expr=ast.Field(chain=["metadata"])),
                ast.Alias(
                    alias="country",
                    expr=ast.Call(
                        name="JSONExtractString", args=[ast.Field(chain=["address"]), ast.Constant(value="country")]
                    ),
                ),
                ast.Alias(alias="cohort", expr=ast.Constant(value=None)),
                ast.Alias(alias="initial_coupon", expr=ast.Constant(value=None)),
                ast.Alias(alias="initial_coupon_id", expr=ast.Constant(value=None)),
            ],
            select_from=ast.JoinExpr(
                alias="outer",
                table=ast.Field(chain=[table.name]),
            ),
        )

        # If there's an invoice table we can generate the cohort entry
        # by looking at the first invoice for each customer
        if invoice_table is not None:
            cohort_alias: ast.Alias | None = next(
                (alias for alias in query.select if isinstance(alias, ast.Alias) and alias.alias == "cohort"), None
            )
            if cohort_alias is not None:
                cohort_alias.expr = ast.Field(chain=["cohort"])

            initial_coupon_alias: ast.Alias | None = next(
                (alias for alias in query.select if isinstance(alias, ast.Alias) and alias.alias == "initial_coupon"),
                None,
            )
            if initial_coupon_alias is not None:
                initial_coupon_alias.expr = ast.Field(chain=["initial_coupon"])

            initial_coupon_id_alias: ast.Alias | None = next(
                (
                    alias
                    for alias in query.select
                    if isinstance(alias, ast.Alias) and alias.alias == "initial_coupon_id"
                ),
                None,
            )
            if initial_coupon_id_alias is not None:
                initial_coupon_id_alias.expr = ast.Field(chain=["initial_coupon_id"])

            if query.select_from is not None and (
                cohort_alias is not None or initial_coupon_alias is not None or initial_coupon_id_alias is not None
            ):
                query.select_from.next_join = ast.JoinExpr(
                    alias="cohort_inner",
                    table=ast.SelectQuery(
                        select=[
                            ast.Field(chain=["customer_id"]),
                            ast.Alias(alias="cohort", expr=get_cohort_expr("min(created_at)")),
                            ast.Alias(
                                alias="initial_coupon",
                                expr=parse_expr("argMin(JSONExtractString(discount, 'coupon', 'name'), created_at)"),
                            ),
                            ast.Alias(
                                alias="initial_coupon_id",
                                expr=parse_expr("argMin(JSONExtractString(discount, 'coupon', 'id'), created_at)"),
                            ),
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
                )

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
