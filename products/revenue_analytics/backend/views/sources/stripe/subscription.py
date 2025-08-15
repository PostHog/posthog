from typing import cast
from collections.abc import Iterable

from posthog.hogql import ast
from posthog.temporal.data_imports.sources.stripe.constants import (
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
)
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.table import DataWarehouseTable

from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_source
from products.revenue_analytics.backend.views.sources.helpers import extract_json_string


def build(handle: SourceHandle) -> Iterable[BuiltQuery]:
    source = handle.source
    if source is None:
        return

    # Get all schemas for the source, avoid calling `filter` and do the filtering on Python-land
    # to avoid n+1 queries
    schemas = source.schemas.all()
    subscription_schema = next((schema for schema in schemas if schema.name == STRIPE_SUBSCRIPTION_RESOURCE_NAME), None)
    if subscription_schema is None:
        return

    subscription_schema = cast(ExternalDataSchema, subscription_schema)
    if subscription_schema.table is None:
        return

    table = cast(DataWarehouseTable, subscription_schema.table)
    prefix = view_prefix_for_source(source)

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
            ast.Alias(alias="plan_id", expr=extract_json_string("plan", "id")),
            ast.Alias(alias="product_id", expr=extract_json_string("plan", "product")),
            ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
            ast.Alias(alias="status", expr=ast.Field(chain=["status"])),
            ast.Alias(alias="started_at", expr=ast.Field(chain=["created_at"])),
            # If has an end date, but it's in the future, then just not include `ended_at`
            ast.Alias(
                alias="ended_at",
                expr=ast.Call(
                    name="if",
                    args=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Gt,
                            left=ast.Field(chain=["ended_at"]),
                            right=ast.Call(name="today", args=[]),
                        ),
                        ast.Constant(value=None),
                        ast.Field(chain=["ended_at"]),
                    ],
                ),
            ),
            ast.Alias(alias="metadata", expr=ast.Field(chain=["metadata"])),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=[table.name])),
    )

    yield BuiltQuery(key=str(table.id), prefix=prefix, query=query)
