from typing import cast

from posthog.hogql import ast

from posthog.temporal.data_imports.sources.stripe.constants import PRODUCT_RESOURCE_NAME as STRIPE_PRODUCT_RESOURCE_NAME

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_source
from products.revenue_analytics.backend.views.schemas.product import SCHEMA


def build(handle: SourceHandle) -> BuiltQuery:
    source = handle.source
    if source is None:
        raise ValueError("Source is required")

    prefix = view_prefix_for_source(source)

    # Get all schemas for the source, avoid calling `filter` and do the filtering on Python-land
    # to avoid n+1 queries
    schemas = source.schemas.all()
    product_schema = next((schema for schema in schemas if schema.name == STRIPE_PRODUCT_RESOURCE_NAME), None)
    if product_schema is None:
        return BuiltQuery(
            key=str(source.id),  # Using source rather than table because table hasn't been found yet
            prefix=prefix,
            query=ast.SelectQuery.empty(columns=SCHEMA.fields),
            test_comments="no_schema",
        )

    product_schema = cast(ExternalDataSchema, product_schema)
    if product_schema.table is None:
        return BuiltQuery(
            key=str(source.id),  # Using source rather than table because table hasn't been found
            prefix=prefix,
            query=ast.SelectQuery.empty(columns=SCHEMA.fields),
            test_comments="no_table",
        )

    table = cast(DataWarehouseTable, product_schema.table)

    query = ast.SelectQuery(
        select=[
            ast.Alias(alias="id", expr=ast.Field(chain=["id"])),
            ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
            ast.Alias(alias="name", expr=ast.Field(chain=["name"])),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=[table.name])),
    )

    return BuiltQuery(key=str(table.id), prefix=prefix, query=query)
