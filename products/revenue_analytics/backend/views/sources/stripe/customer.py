from typing import cast

from django.db.models import QuerySet

from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery
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
from products.revenue_analytics.backend.views.sources.constants import (
    POSTHOG_PERSON_DISTINCT_ID_METADATA_KEY,
    POSTHOG_PERSON_DISTINCT_ID_SOURCE_METADATA_KEY,
)
from products.revenue_analytics.backend.views.sources.helpers import extract_json_string, get_cohort_expr

_METADATA_TO_MAP_EXPR = (
    "mapFromArrays("
    "JSONExtractKeys(ifNull(metadata, '{}')), "
    "arrayMap(k -> JSONExtractString(ifNull(metadata, '{}'), k), JSONExtractKeys(ifNull(metadata, '{}')))"
    ")"
)

_ENRICHED_METADATA_EXPR = parse_expr(
    f"""
    if(
        JSONExtractString(metadata, {{distinct_id_key}}) != '',
        toJSONString(mapUpdate({_METADATA_TO_MAP_EXPR}, map({{source_key}}, 'customer'))),
        if(
            resolved_distinct_id != '',
            toJSONString(mapUpdate({_METADATA_TO_MAP_EXPR}, map(
                {{distinct_id_key}}, resolved_distinct_id,
                {{source_key}}, resolved_source
            ))),
            metadata
        )
    )
    """,
    placeholders={
        "distinct_id_key": ast.Constant(value=POSTHOG_PERSON_DISTINCT_ID_METADATA_KEY),
        "source_key": ast.Constant(value=POSTHOG_PERSON_DISTINCT_ID_SOURCE_METADATA_KEY),
    },
)


def build(handle: SourceHandle) -> BuiltQuery:
    source = handle.source
    if source is None:
        raise ValueError("Source is required")

    prefix = view_prefix_for_source(source)

    # Get all schemas for the source, avoid calling `filter` and do the filtering on Python-land to avoid n+1 queries
    schemas = source.schemas.all()
    customer_schema = next((schema for schema in schemas if schema.name == STRIPE_CUSTOMER_RESOURCE_NAME), None)
    if customer_schema is None:
        return BuiltQuery(
            key=str(source.id),
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

    customer_table = cast(DataWarehouseTable, customer_schema.table)
    invoice_table = _get_table(schemas, STRIPE_INVOICE_RESOURCE_NAME)
    subscription_table = _get_table(schemas, STRIPE_SUBSCRIPTION_RESOURCE_NAME)
    charge_table = _get_table(schemas, STRIPE_CHARGE_RESOURCE_NAME)

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
            table=ast.Field(chain=[customer_table.name]),
        ),
    )

    # If there's an invoice table we can generate the cohort entry
    # by looking at the first invoice for each customer.
    # Cohort is the month of a customer's first invoice
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

    child_tables: list[tuple[str, DataWarehouseTable]] = []
    if subscription_table is not None:
        child_tables.append(("subscription", subscription_table))
    if charge_table is not None:
        child_tables.append(("charge", charge_table))
    if invoice_table is not None:
        child_tables.append(("invoice", invoice_table))

    if child_tables:
        query = _build_resolved_distinct_id_query(child_tables=child_tables, query=query)

    return BuiltQuery(key=str(customer_table.id), prefix=prefix, query=query)


def _get_table(schemas: QuerySet[ExternalDataSchema], schema_name: str) -> DataWarehouseTable | None:
    schema = next((schema for schema in schemas if schema.name == schema_name), None)
    if schema is None:
        return None

    table = schema.table
    if table is not None:
        table = cast(DataWarehouseTable, table)

    return table


def _build_resolved_distinct_id_query(
    child_tables: list[tuple[str, DataWarehouseTable]], query: SelectQuery
) -> SelectQuery:
    resolved_subquery = _build_resolved_subquery(child_tables)

    last_join = query.select_from
    if last_join is not None:
        while last_join.next_join is not None:
            last_join = last_join.next_join
        last_join.next_join = ast.JoinExpr(
            alias="resolved",
            table=resolved_subquery,
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                constraint_type="ON",
                expr=ast.CompareOperation(
                    left=ast.Field(chain=["resolved", "customer_id"]),
                    right=ast.Field(chain=["outer", "id"]),
                    op=ast.CompareOperationOp.Eq,
                ),
            ),
        )

    query.select.append(
        ast.Alias(
            alias="resolved_distinct_id",
            expr=ast.Call(
                name="ifNull", args=[ast.Field(chain=["resolved", "resolved_distinct_id"]), ast.Constant(value="")]
            ),
        ),
    )
    query.select.append(
        ast.Alias(
            alias="resolved_source",
            expr=ast.Call(
                name="ifNull", args=[ast.Field(chain=["resolved", "resolved_source"]), ast.Constant(value="")]
            ),
        ),
    )

    outer_query = ast.SelectQuery(
        select=[
            ast.Alias(alias="id", expr=ast.Field(chain=["id"])),
            ast.Alias(alias="source_label", expr=ast.Field(chain=["source_label"])),
            ast.Alias(alias="timestamp", expr=ast.Field(chain=["timestamp"])),
            ast.Alias(alias="name", expr=ast.Field(chain=["name"])),
            ast.Alias(alias="email", expr=ast.Field(chain=["email"])),
            ast.Alias(alias="phone", expr=ast.Field(chain=["phone"])),
            ast.Alias(alias="address", expr=ast.Field(chain=["address"])),
            ast.Alias(alias="metadata", expr=_ENRICHED_METADATA_EXPR),
            ast.Alias(alias="country", expr=ast.Field(chain=["country"])),
            ast.Alias(alias="cohort", expr=ast.Field(chain=["cohort"])),
            ast.Alias(alias="initial_coupon", expr=ast.Field(chain=["initial_coupon"])),
            ast.Alias(alias="initial_coupon_id", expr=ast.Field(chain=["initial_coupon_id"])),
        ],
        select_from=ast.JoinExpr(table=query, alias="inner"),
    )

    return outer_query


def _build_resolved_subquery(child_tables: list[tuple[str, DataWarehouseTable]]) -> ast.SelectQuery:
    union_legs = [_build_child_union_leg(table.name, label) for label, table in child_tables]

    union_query: ast.SelectQuery | ast.SelectSetQuery = union_legs[0]
    if len(union_legs) > 1:
        union_query = ast.SelectSetQuery(
            initial_select_query=union_legs[0],
            subsequent_select_queries=[
                ast.SelectSetNode(select_query=leg, set_operator="UNION ALL") for leg in union_legs[1:]
            ],
        )

    return ast.SelectQuery(
        select=[
            ast.Field(chain=["customer_id"]),
            ast.Alias(
                alias="resolved_distinct_id",
                expr=ast.Call(name="argMax", args=[ast.Field(chain=["distinct_id"]), ast.Field(chain=["created_at"])]),
            ),
            ast.Alias(
                alias="resolved_source",
                expr=ast.Call(name="argMax", args=[ast.Field(chain=["source_ref"]), ast.Field(chain=["created_at"])]),
            ),
        ],
        select_from=ast.JoinExpr(table=union_query, alias="child_meta"),
        group_by=[ast.Field(chain=["customer_id"])],
    )


def _build_child_union_leg(table_name: str, label: str) -> ast.SelectQuery | ast.SelectSetQuery:
    # nosemgrep: hogql-fstring-audit (table_name is internal Stripe table name from system schema, not user input)
    return parse_select(
        f"""
        SELECT
            customer_id,
            JSONExtractString(metadata, {{metadata_key}}) AS distinct_id,
            concat({{label}}, '::', id) AS source_ref,
            created_at
        FROM {table_name}
        WHERE JSONExtractString(metadata, {{metadata_key}}) != ''
        """,
        placeholders={
            "metadata_key": ast.Constant(value=POSTHOG_PERSON_DISTINCT_ID_METADATA_KEY),
            "label": ast.Constant(value=label),
        },
    )
