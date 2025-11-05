from typing import cast

from posthog.hogql import ast

from posthog.temporal.data_imports.sources.stripe.constants import (
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
)

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_source
from products.revenue_analytics.backend.views.schemas.customer import SCHEMA
from products.revenue_analytics.backend.views.sources.helpers import extract_json_string, get_cohort_expr


def build(handle: SourceHandle) -> BuiltQuery:
    source = handle.source
    if source is None:
        raise ValueError("Source is required")

    prefix = view_prefix_for_source(source)

    # Get all schemas for the source, avoid calling `filter` and do the filtering on Python-land
    # to avoid n+1 queries
    schemas = source.schemas.all()
    customer_schema = next((schema for schema in schemas if schema.name == STRIPE_CUSTOMER_RESOURCE_NAME), None)
    if customer_schema is None:
        return BuiltQuery(
            key=str(source.id),  # Using source rather than table because table hasn't been found yet
            prefix=prefix,
            query=ast.SelectQuery.empty(columns=SCHEMA.fields),
            test_comments="no_schema",
        )

    customer_schema = cast(ExternalDataSchema, customer_schema)
    if customer_schema.table is None:
        return BuiltQuery(
            key=str(source.id),  # Using source rather than table because table hasn't been found
            prefix=prefix,
            query=ast.SelectQuery.empty(columns=SCHEMA.fields),
            test_comments="no_table",
        )

    invoice_schema = next((schema for schema in schemas if schema.name == STRIPE_INVOICE_RESOURCE_NAME), None)
    invoice_table = None
    if invoice_schema is not None:
        invoice_schema = cast(ExternalDataSchema, invoice_schema)
        invoice_table = invoice_schema.table
        if invoice_table is not None:
            invoice_table = cast(DataWarehouseTable, invoice_table)

    table = cast(DataWarehouseTable, customer_schema.table)

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
                expr=extract_json_string("address", "country"),
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
            (alias for alias in query.select if isinstance(alias, ast.Alias) and alias.alias == "initial_coupon_id"),
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
                            expr=ast.Call(
                                name="argMin",
                                args=[
                                    extract_json_string("discount", "coupon", "name"),
                                    ast.Field(chain=["created_at"]),
                                ],
                            ),
                        ),
                        ast.Alias(
                            alias="initial_coupon_id",
                            expr=ast.Call(
                                name="argMin",
                                args=[
                                    extract_json_string("discount", "coupon", "id"),
                                    ast.Field(chain=["created_at"]),
                                ],
                            ),
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

    return BuiltQuery(key=str(table.id), prefix=prefix, query=query)
