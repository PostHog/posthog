from typing import cast

from posthog.hogql import ast
from posthog.models.team.team import Team
from posthog.schema import DatabaseSchemaManagedViewTableKind
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    StringDatabaseField,
    FieldOrTable,
)
from posthog.hogql.database.schema.exchange_rate import (
    convert_currency_call,
)
from products.revenue_analytics.backend.views.currency_helpers import (
    BASE_CURRENCY_FIELDS,
    currency_aware_divider,
    currency_aware_amount,
    is_zero_decimal_in_stripe,
)
from .revenue_analytics_base_view import RevenueAnalyticsBaseView
from posthog.temporal.data_imports.pipelines.stripe.constants import (
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
)

SOURCE_VIEW_SUFFIX = "invoice_item_revenue_view"

FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "product_id": StringDatabaseField(name="product_id"),
    **BASE_CURRENCY_FIELDS,
}


def extract_json_string(field: str, *path: str) -> ast.Call:
    return ast.Call(
        name="JSONExtractString",
        args=[
            ast.Field(chain=[field]),
            *[ast.Constant(value=p) for p in path],
        ],
    )


class RevenueAnalyticsInvoiceItemView(RevenueAnalyticsBaseView):
    @staticmethod
    def get_database_schema_table_kind() -> DatabaseSchemaManagedViewTableKind:
        return DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_INVOICE_ITEM

    # TODO: Need to figure out a way to support this for events
    # We'll need either support for arbitrary HogQL here (which we need in general anyway)
    # or force some kind of structure to list what an "invoice" is, and how to compute the revenue from it
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
        invoice_schema = next((schema for schema in schemas if schema.name == STRIPE_INVOICE_RESOURCE_NAME), None)
        if invoice_schema is None:
            return []

        invoice_schema = cast(ExternalDataSchema, invoice_schema)
        if invoice_schema.table is None:
            return []

        invoice_table = cast(DataWarehouseTable, invoice_schema.table)
        team = invoice_table.team

        # Even though we need a string query for the view,
        # using an ast allows us to comment what each field means, and
        # avoid manual interpolation of constants, leaving that to the HogQL printer
        query = ast.SelectQuery(
            select=[
                # Base fields to allow insights to work (need `distinct_id` AND `timestamp` fields)
                ast.Alias(alias="id", expr=ast.Field(chain=["id"])),
                ast.Alias(alias="timestamp", expr=ast.Field(chain=["created_at"])),
                ast.Field(chain=["product_id"]),
                # Compute the original currency, converting to uppercase to match the currency code in the `exchange_rate` table
                ast.Alias(
                    alias="original_currency",
                    expr=ast.Call(name="upper", args=[ast.Field(chain=["currency"])]),
                ),
                # Compute the original amount in the original currency
                # by looking at the captured amount, effectively ignoring refunded value
                ast.Alias(
                    alias="original_amount",
                    expr=ast.Call(
                        name="toDecimal",
                        args=[
                            ast.Field(chain=["amount_captured"]),
                            ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
                        ],
                    ),
                ),
                # Compute whether the original currency is a zero-decimal currency
                # by comparing it against a list of known zero-decimal currencies
                # in Stripe's API
                ast.Alias(
                    alias="enable_currency_aware_divider",
                    expr=is_zero_decimal_in_stripe(ast.Field(chain=["original_currency"])),
                ),
                # Compute the amount decimal divider, which is 1 for zero-decimal currencies and 100 for others
                # This is used to convert the original amount to the adjusted amount
                currency_aware_divider(),
                # Compute the adjusted original amount, which is the original amount divided by the amount decimal divider
                currency_aware_amount(),
                # Expose the base/converted currency, which is the base currency from the team's revenue config
                ast.Alias(alias="currency", expr=ast.Constant(value=team.base_currency)),
                # Convert the adjusted original amount to the base currency
                ast.Alias(
                    alias="amount",
                    expr=convert_currency_call(
                        amount=ast.Field(chain=["currency_aware_amount"]),
                        currency_from=ast.Field(chain=["original_currency"]),
                        currency_to=ast.Field(chain=["currency"]),
                        timestamp=ast.Call(
                            name="_toDate",
                            args=[
                                ast.Call(
                                    name="ifNull",
                                    args=[
                                        ast.Field(chain=["timestamp"]),
                                        ast.Call(name="toDateTime", args=[ast.Constant(value=0)]),
                                    ],
                                ),
                            ],
                        ),
                    ),
                ),
            ],
            # Heavy work for this query is done here in the subquery
            # by exploding the `lines.data[].price.product` field
            select_from=ast.JoinExpr(
                alias="invoice",
                table=ast.SelectQuery(
                    select=[
                        ast.Field(chain=["id"]),
                        ast.Field(chain=["created_at"]),
                        # Explode the `lines.data` field into an individual row per item
                        ast.Alias(
                            alias="data",
                            expr=ast.Call(
                                name="arrayJoin",
                                args=[
                                    ast.Call(
                                        name="JSONExtractArrayRaw",
                                        args=[
                                            ast.Call(name="assumeNotNull", args=[ast.Field(chain=["lines", "data"])])
                                        ],
                                    ),
                                ],
                            ),
                        ),
                        ast.Alias(alias="amount_captured", expr=extract_json_string("data", "amount")),
                        ast.Alias(alias="currency", expr=extract_json_string("data", "currency")),
                        ast.Alias(alias="product_id", expr=extract_json_string("data", "price", "product")),
                    ],
                    select_from=ast.JoinExpr(table=ast.Field(chain=[invoice_table.name])),
                    # Only include paid invoices because they're the ones that represent revenue
                    where=ast.Field(chain=["paid"]),
                ),
            ),
        )

        return [
            RevenueAnalyticsInvoiceItemView(
                id=str(invoice_table.id),
                name=RevenueAnalyticsBaseView.get_view_name_for_source(source, SOURCE_VIEW_SUFFIX),
                prefix=RevenueAnalyticsBaseView.get_view_prefix_for_source(source),
                query=query.to_hogql(),
                fields=FIELDS,
                source_id=str(source.id),
            )
        ]
