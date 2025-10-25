from typing import cast

from posthog.hogql import ast
from posthog.hogql.database.schema.exchange_rate import EXCHANGE_RATE_DECIMAL_PRECISION, convert_currency_call

from posthog.temporal.data_imports.sources.stripe.constants import CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.table import DataWarehouseTable

from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_source
from products.revenue_analytics.backend.views.schemas.charge import SCHEMA
from products.revenue_analytics.backend.views.sources.helpers import (
    currency_aware_amount,
    currency_aware_divider,
    is_zero_decimal_in_stripe,
)


def build(handle: SourceHandle) -> BuiltQuery:
    source = handle.source
    if source is None:
        raise ValueError("Source is required")

    prefix = view_prefix_for_source(source)

    # Get all schemas for the source, avoid calling `filter` and do the filtering on Python-land
    # to avoid n+1 queries
    schemas = source.schemas.all()
    charge_schema = next((schema for schema in schemas if schema.name == STRIPE_CHARGE_RESOURCE_NAME), None)
    if charge_schema is None:
        return BuiltQuery(
            key=str(source.id),  # Using source rather than table because table hasn't been found yet
            prefix=prefix,
            query=ast.SelectQuery.empty(columns=SCHEMA.fields),
            test_comments="no_schema",
        )

    charge_schema = cast(ExternalDataSchema, charge_schema)
    if charge_schema.table is None:
        return BuiltQuery(
            key=str(source.id),  # Using source rather than table because table hasn't been found
            prefix=prefix,
            query=ast.SelectQuery.empty(columns=SCHEMA.fields),
            test_comments="no_table",
        )

    table = cast(DataWarehouseTable, charge_schema.table)
    team = table.team

    query = ast.SelectQuery(
        select=[
            # Base fields to allow insights to work (need `distinct_id` AND `timestamp` fields)
            ast.Alias(alias="id", expr=ast.Field(chain=["id"])),
            ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
            ast.Alias(alias="timestamp", expr=ast.Field(chain=["created_at"])),
            # Useful for cross joins
            ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
            ast.Alias(alias="invoice_id", expr=ast.Field(chain=["invoice_id"])),
            # Empty, but required for the `events` view to work
            ast.Alias(alias="session_id", expr=ast.Constant(value=None)),
            ast.Alias(alias="event_name", expr=ast.Constant(value=None)),
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
        # Simple query, simply refer to the `stripe_charge` table
        select_from=ast.JoinExpr(table=ast.Field(chain=[table.name])),
        # Only include succeeded charges because they're the ones that represent revenue
        where=ast.CompareOperation(
            left=ast.Field(chain=["status"]),
            right=ast.Constant(value="succeeded"),
            op=ast.CompareOperationOp.Eq,
        ),
    )

    return BuiltQuery(key=str(table.id), prefix=prefix, query=query)
