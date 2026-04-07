from collections.abc import Callable
from typing import cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
)

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_source
from products.revenue_analytics.backend.views.schemas.customer import SCHEMA
from products.revenue_analytics.backend.views.sources.helpers import extract_json_string, get_cohort_expr

POSTHOG_PERSON_DISTINCT_ID_METADATA_KEY = "posthog_person_distinct_id"
POSTHOG_PERSON_DISTINCT_ID_SOURCE_METADATA_KEY = "posthog_person_distinct_id_source"


def _build_child_distinct_id_subquery(table_name: str, alias: str) -> ast.SelectQuery:
    return parse_select(
        f"""
        SELECT
            {alias}.customer_id AS customer_id,
            argMax(JSONExtractString({alias}.metadata, {{metadata_key}}), {alias}.created_at) AS distinct_id,
            argMax({alias}.id, {alias}.created_at) AS source_id,
            max({alias}.created_at) AS created_at
        FROM {table_name} AS {alias}
        WHERE JSONExtractString({alias}.metadata, {{metadata_key}}) != ''
        GROUP BY {alias}.customer_id
        """,
        placeholders={"metadata_key": ast.Constant(value=POSTHOG_PERSON_DISTINCT_ID_METADATA_KEY)},
    )


_METADATA_TO_MAP_EXPR = (
    "mapFromArrays("
    "JSONExtractKeys(ifNull(metadata, '{}')), "
    "arrayMap(k -> JSONExtractString(ifNull(metadata, '{}'), k), JSONExtractKeys(ifNull(metadata, '{}')))"
    ")"
)


def _build_enriched_metadata_expr(
    child_tables: list[tuple[str, str]],
) -> ast.Expr:
    resolved_distinct_id = _build_resolved_distinct_id_expr(child_tables)
    resolved_source = _build_resolved_source_expr(child_tables)

    return parse_expr(
        f"""
        if(
            JSONExtractString(metadata, {{distinct_id_key}}) != '',
            toJSONString(mapUpdate({_METADATA_TO_MAP_EXPR}, map({{source_key}}, 'customer'))),
            if(
                {{resolved_distinct_id}} != '',
                toJSONString(mapUpdate({_METADATA_TO_MAP_EXPR}, map(
                    {{distinct_id_key}}, ifNull({{resolved_distinct_id}}, ''),
                    {{source_key}}, ifNull({{resolved_source}}, '')
                ))),
                metadata
            )
        )
        """,
        placeholders={
            "distinct_id_key": ast.Constant(value=POSTHOG_PERSON_DISTINCT_ID_METADATA_KEY),
            "source_key": ast.Constant(value=POSTHOG_PERSON_DISTINCT_ID_SOURCE_METADATA_KEY),
            "resolved_distinct_id": resolved_distinct_id,
            "resolved_source": resolved_source,
        },
    )


def _build_freshest_child_multiif(
    child_tables: list[tuple[str, str]],
    value_fn: Callable[[str, str], ast.Expr],
) -> ast.Expr:
    """Build a multiIf that picks a value from the freshest child table.

    Args:
        child_tables: List of (join_alias, source_label) tuples
        value_fn: Given (alias, label), returns the ast.Expr to use as the "then" value
    """
    if not child_tables:
        return ast.Constant(value="")

    zero_dt = ast.Call(name="toDateTime", args=[ast.Constant(value=0)])
    args: list[ast.Expr] = []

    for alias, label in child_tables:
        this_created = ast.Field(chain=[alias, "created_at"])
        this_distinct_id = ast.Field(chain=[alias, "distinct_id"])

        has_value = ast.And(
            exprs=[
                ast.Call(name="isNotNull", args=[this_distinct_id]),
                ast.CompareOperation(
                    left=this_distinct_id,
                    right=ast.Constant(value=""),
                    op=ast.CompareOperationOp.NotEq,
                ),
            ]
        )

        freshest_conditions = []
        for other_alias, _ in child_tables:
            if other_alias == alias:
                continue
            other_created = ast.Field(chain=[other_alias, "created_at"])
            freshest_conditions.append(
                ast.CompareOperation(
                    left=this_created,
                    right=ast.Call(name="coalesce", args=[other_created, zero_dt]),
                    op=ast.CompareOperationOp.GtEq,
                )
            )

        if freshest_conditions:
            condition = ast.And(exprs=[has_value, *freshest_conditions])
        else:
            condition = has_value

        args.append(condition)
        args.append(value_fn(alias, label))

    args.append(ast.Constant(value=""))
    return ast.Call(name="multiIf", args=args)


def _build_resolved_distinct_id_expr(child_tables: list[tuple[str, str]]) -> ast.Expr:
    return _build_freshest_child_multiif(
        child_tables,
        value_fn=lambda alias, _label: ast.Field(chain=[alias, "distinct_id"]),
    )


def _build_resolved_source_expr(child_tables: list[tuple[str, str]]) -> ast.Expr:
    return _build_freshest_child_multiif(
        child_tables,
        value_fn=lambda alias, label: ast.Call(
            name="concat",
            args=[ast.Constant(value=f"{label}::"), ast.Field(chain=[alias, "source_id"])],
        ),
    )


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

    subscription_schema = next((schema for schema in schemas if schema.name == STRIPE_SUBSCRIPTION_RESOURCE_NAME), None)
    subscription_table = None
    if subscription_schema is not None:
        subscription_schema = cast(ExternalDataSchema, subscription_schema)
        subscription_table = subscription_schema.table
        if subscription_table is not None:
            subscription_table = cast(DataWarehouseTable, subscription_table)

    charge_schema = next((schema for schema in schemas if schema.name == STRIPE_CHARGE_RESOURCE_NAME), None)
    charge_table = None
    if charge_schema is not None:
        charge_schema = cast(ExternalDataSchema, charge_schema)
        charge_table = charge_schema.table
        if charge_table is not None:
            charge_table = cast(DataWarehouseTable, charge_table)

    table = cast(DataWarehouseTable, customer_schema.table)

    query = ast.SelectQuery(
        select=[
            ast.Alias(alias="id", expr=ast.Field(chain=["outer", "id"])),
            ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
            ast.Alias(alias="timestamp", expr=ast.Field(chain=["outer", "created_at"])),
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

    child_tables: list[tuple[str, str]] = []
    child_join_configs: list[tuple[str, str, DataWarehouseTable]] = []

    if subscription_table is not None:
        child_join_configs.append(("sub", "subscription", subscription_table))
    if charge_table is not None:
        child_join_configs.append(("chg", "charge", charge_table))
    if invoice_table is not None:
        child_join_configs.append(("inv", "invoice", invoice_table))

    last_join = query.select_from
    if last_join is not None:
        while last_join.next_join is not None:
            last_join = last_join.next_join

    for alias, label, child_table in child_join_configs:
        child_tables.append((alias, label))
        new_join = ast.JoinExpr(
            alias=alias,
            table=_build_child_distinct_id_subquery(child_table.name, alias),
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                constraint_type="ON",
                expr=ast.CompareOperation(
                    left=ast.Field(chain=[alias, "customer_id"]),
                    right=ast.Field(chain=["outer", "id"]),
                    op=ast.CompareOperationOp.Eq,
                ),
            ),
        )
        if last_join is not None:
            last_join.next_join = new_join
            last_join = new_join

    if child_tables:
        metadata_alias: ast.Alias | None = next(
            (alias for alias in query.select if isinstance(alias, ast.Alias) and alias.alias == "metadata"), None
        )
        if metadata_alias is not None:
            metadata_alias.expr = _build_enriched_metadata_expr(child_tables)

    return BuiltQuery(key=str(table.id), prefix=prefix, query=query)
