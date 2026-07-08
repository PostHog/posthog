"""Shared plumbing for SQL-based data-import sources.

This package concentrates the orchestration and safety primitives that used to
be copy-pasted across every SQL source (`postgres/postgres.py`, `mysql/mysql.py`,
etc). A new SQL source should be implementable by subclassing `SQLSource` and
providing a small set of driver-specific hooks — connection, identifier quoter,
incremental-field filter, and schema/row discovery.

Only the types that existed in the old `common/sql.py` are re-exported from
this package's root so existing `from ...common.sql import Column, Table`
imports keep working. New callers should import from the submodules directly.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.identifiers import (
    AnsiIdentifierQuoter,
    BacktickIdentifierQuoter,
    BracketIdentifierQuoter,
    IdentifierQuoter,
    InvalidIdentifierError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.implementation import TableStats
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.incremental import (
    IncrementalFieldFilter,
    build_incremental_fields,
    initial_value_for_incremental_type,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.metadata import (
    extract_available_column_names,
    sql_schema_metadata,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    ColumnTypeCategory,
    RowFilter,
    RowFilterValidationError,
    ValidatedRowFilter,
    classify_column_type,
    is_multi_value_operator,
    normalize_operator,
    render_named_conditions,
    render_positional_conditions,
    validate_and_coerce_row_filters,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.projection import (
    compute_projected_columns,
    filter_columns_by_enabled_columns,
    filter_dwh_columns_by_enabled_columns,
    format_projected_select_clause,
    project_arrow_columns,
    prune_enabled_columns,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.query_builder import (
    ParamStyle,
    SafeSQL,
    SelectQueryBuilder,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.types import (
    Column,
    ColumnType,
    Table,
    TableBase,
    TableReference,
    TableSchemas,
    resolve_detected_primary_keys,
)

__all__ = [
    "AnsiIdentifierQuoter",
    "BacktickIdentifierQuoter",
    "BracketIdentifierQuoter",
    "Column",
    "ColumnType",
    "ColumnTypeCategory",
    "IdentifierQuoter",
    "IncrementalFieldFilter",
    "InvalidIdentifierError",
    "ParamStyle",
    "RowFilter",
    "RowFilterValidationError",
    "SafeSQL",
    "SelectQueryBuilder",
    "Table",
    "TableBase",
    "TableReference",
    "TableSchemas",
    "TableStats",
    "ValidatedRowFilter",
    "build_incremental_fields",
    "classify_column_type",
    "compute_projected_columns",
    "extract_available_column_names",
    "filter_columns_by_enabled_columns",
    "filter_dwh_columns_by_enabled_columns",
    "format_projected_select_clause",
    "initial_value_for_incremental_type",
    "is_multi_value_operator",
    "normalize_operator",
    "project_arrow_columns",
    "prune_enabled_columns",
    "render_named_conditions",
    "render_positional_conditions",
    "resolve_detected_primary_keys",
    "sql_schema_metadata",
    "validate_and_coerce_row_filters",
]
