from collections.abc import Iterable
from typing import cast

from posthog.hogql import ast

from posthog.temporal.data_imports.sources.stripe.constants import (
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
)
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.table import DataWarehouseTable

from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_source
from products.revenue_analytics.backend.views.schemas.subscription import SCHEMA
from products.revenue_analytics.backend.views.sources.helpers import extract_json_string


def build(handle: SourceHandle) -> Iterable[BuiltQuery]:
    source = handle.source
    if source is None:
        return

    prefix = view_prefix_for_source(source)

    # Get all schemas for the source, avoid calling `filter` and do the filtering on Python-land
    # to avoid n+1 queries
    schemas = source.schemas.all()
    subscription_schema = next((schema for schema in schemas if schema.name == STRIPE_SUBSCRIPTION_RESOURCE_NAME), None)
    if subscription_schema is None:
        yield BuiltQuery(
            key=f"{prefix}.no_source", prefix=prefix, query=ast.SelectQuery.empty(columns=list(SCHEMA.fields.keys()))
        )
        return

    subscription_schema = cast(ExternalDataSchema, subscription_schema)
    if subscription_schema.table is None:
        yield BuiltQuery(
            key=f"{prefix}.no_table", prefix=prefix, query=ast.SelectQuery.empty(columns=list(SCHEMA.fields.keys()))
        )
        return

    table = cast(DataWarehouseTable, subscription_schema.table)

    query = ast.SelectQuery(
        select=[
            ast.Alias(alias="id", expr=ast.Field(chain=["id"])),
            ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
            ast.Alias(alias="plan_id", expr=extract_json_string("plan", "id")),
            ast.Alias(alias="product_id", expr=extract_json_string("plan", "product")),
            ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
            ast.Alias(alias="status", expr=ast.Field(chain=["status"])),
            ast.Alias(alias="started_at", expr=ast.Field(chain=["created_at"])),
            ast.Alias(alias="ended_at", expr=ast.Field(chain=["ended_at"])),
            ast.Alias(alias="metadata", expr=ast.Field(chain=["metadata"])),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=[table.name])),
    )

    yield BuiltQuery(key=str(table.id), prefix=prefix, query=query)
