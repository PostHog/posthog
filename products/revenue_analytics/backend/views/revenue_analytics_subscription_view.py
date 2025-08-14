from .revenue_analytics_base_view import RevenueAnalyticsBaseView
from typing import cast
from posthog.hogql import ast
from posthog.models.team.team import Team
from posthog.schema import DatabaseSchemaManagedViewTableKind
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.types import ExternalDataSourceType
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    StringDatabaseField,
    FieldOrTable,
)
from .revenue_analytics_base_view import events_expr_for_team

SOURCE_VIEW_SUFFIX = "subscription_revenue_view"
EVENTS_VIEW_SUFFIX = "subscription_events_revenue_view"

FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "source_label": StringDatabaseField(name="source_label"),
    "plan_id": StringDatabaseField(name="plan_id"),
    "product_id": StringDatabaseField(name="product_id"),
    "customer_id": StringDatabaseField(name="customer_id"),
    "status": StringDatabaseField(name="status"),
    "started_at": DateTimeDatabaseField(name="started_at"),
    "ended_at": DateTimeDatabaseField(name="ended_at"),
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

    @classmethod
    def for_events(cls, team: "Team") -> list["RevenueAnalyticsBaseView"]:
        if len(team.revenue_analytics_config.events) == 0:
            return []

        revenue_config = team.revenue_analytics_config

        queries: list[tuple[str, str, ast.SelectQuery]] = []
        for event in revenue_config.events:
            if event.subscriptionProperty is None:
                continue

            prefix = RevenueAnalyticsBaseView.get_view_prefix_for_event(event.eventName)

            events_query = ast.SelectQuery(
                select=[
                    ast.Alias(alias="person_id", expr=ast.Field(chain=["person", "id"])),
                    ast.Alias(
                        alias="subscription_id", expr=ast.Field(chain=["properties", event.subscriptionProperty])
                    ),
                    ast.Alias(
                        alias="product_id",
                        expr=ast.Call(name="min", args=[ast.Field(chain=["properties", event.productProperty])])
                        if event.productProperty
                        else ast.Constant(value=None),
                    ),
                    ast.Alias(alias="min_timestamp", expr=ast.Call(name="min", args=[ast.Field(chain=["timestamp"])])),
                    ast.Alias(alias="max_timestamp", expr=ast.Call(name="max", args=[ast.Field(chain=["timestamp"])])),
                ],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                where=events_expr_for_team(team),
                group_by=[
                    ast.Field(chain=["subscription_id"]),
                    ast.Field(chain=["person_id"]),
                ],
            )

            query = ast.SelectQuery(
                select=[
                    ast.Alias(alias="id", expr=ast.Field(chain=["subscription_id"])),
                    ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
                    ast.Alias(alias="plan_id", expr=ast.Constant(value=None)),
                    ast.Alias(alias="product_id", expr=ast.Field(chain=["product_id"])),
                    ast.Alias(
                        alias="customer_id", expr=ast.Call(name="toString", args=[ast.Field(chain=["person_id"])])
                    ),
                    ast.Alias(alias="status", expr=ast.Constant(value=None)),
                    ast.Alias(alias="started_at", expr=ast.Field(chain=["min_timestamp"])),
                    # If the last event is not `event.subscriptionDropoffDays` in the past, consider the subscription to still be active
                    # Otherwise, consider it ended at the last event
                    ast.Alias(
                        alias="ended_at",
                        expr=ast.Call(
                            name="if",
                            args=[
                                ast.CompareOperation(
                                    op=ast.CompareOperationOp.Gt,
                                    left=ast.Call(
                                        name="addDays",
                                        args=[
                                            ast.Field(chain=["max_timestamp"]),
                                            ast.Constant(value=event.subscriptionDropoffDays),
                                        ],
                                    ),
                                    right=ast.Call(name="today", args=[]),
                                ),
                                ast.Constant(value=None),
                                ast.Field(chain=["max_timestamp"]),
                            ],
                        ),
                    ),
                    ast.Alias(alias="metadata", expr=ast.Constant(value=None)),
                ],
                select_from=ast.JoinExpr(table=events_query),
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["started_at"]), order="DESC")],
            )

            queries.append((event.eventName, prefix, query))

        return [
            RevenueAnalyticsSubscriptionView(
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
        from posthog.temporal.data_imports.sources.stripe.constants import (
            SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
        )

        # Currently only works for stripe sources
        if not source.source_type == ExternalDataSourceType.STRIPE:
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
