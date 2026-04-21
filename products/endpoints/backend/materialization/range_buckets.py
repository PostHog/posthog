from posthog.hogql import ast

from products.endpoints.backend.materialization.types import MaterializableVariable

RANGE_OPS = frozenset(
    {
        ast.CompareOperationOp.GtEq,
        ast.CompareOperationOp.Gt,
        ast.CompareOperationOp.Lt,
        ast.CompareOperationOp.LtEq,
    }
)


SUPPORTED_BUCKET_FUNCTIONS: dict[str, str] = {
    "minute": "toStartOfMinute",
    "fifteen_minutes": "toStartOfFifteenMinutes",
    "hour": "toStartOfHour",
    "day": "toStartOfDay",
    "week": "toStartOfWeek",
    "month": "toStartOfMonth",
}


def _is_property_column(column_chain: list[str]) -> bool:
    """Check if a column chain references a properties field (e.g. properties.price)."""
    return "properties" in column_chain


def _detect_range_variables(
    variables: list[MaterializableVariable],
    bucket_overrides: dict[str, str] | None = None,
) -> None:
    """Detect range variables and set bucket_fn for bucketed materialization.

    Any variable with a range operator on a plain column (no column_ast)
    gets bucket_fn set. For single-bound ranges, we materialize all data
    bucketed and filter at read time with the user's value.

    Properties columns (e.g. properties.price) are skipped unless the user
    explicitly provides a bucket_override — bucket functions like toStartOfDay
    only make sense on DateTime columns, not on string/numeric properties.
    """
    for var in variables:
        if var.column_ast is not None:
            continue
        if var.operator not in RANGE_OPS:
            continue

        col_key = ".".join(var.column_chain) if var.column_chain else var.column_expression

        if bucket_overrides and col_key in bucket_overrides:
            override = bucket_overrides[col_key]
            if override not in SUPPORTED_BUCKET_FUNCTIONS:
                raise ValueError(
                    f"Unsupported bucket override '{override}'. Supported: {list(SUPPORTED_BUCKET_FUNCTIONS.keys())}"
                )
            var.bucket_fn = SUPPORTED_BUCKET_FUNCTIONS[override]
        elif not _is_property_column(var.column_chain):
            var.bucket_fn = "toStartOfDay"
