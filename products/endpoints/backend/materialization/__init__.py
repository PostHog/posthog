"""Public API for endpoint variable materialization.

Production code should import from this module. Private helpers (leading underscore)
live on the specific submodules — tests and internal code should reach for them
via explicit submodule paths (e.g. ``from .cte_propagation import _build_cte_read_graph``).
"""

from products.endpoints.backend.materialization.aggregates import (
    REAGGREGATABLE_BASE_FUNCTIONS,
    AggregateReaggregation,
    extract_aggregate_name,
    get_reaggregation,
)
from products.endpoints.backend.materialization.analyzer import analyze_variables_for_materialization
from products.endpoints.backend.materialization.cte_propagation import DownstreamCTEPlan, DownstreamCTEShape
from products.endpoints.backend.materialization.insight_conversion import convert_insight_query_to_hogql
from products.endpoints.backend.materialization.range_buckets import SUPPORTED_BUCKET_FUNCTIONS
from products.endpoints.backend.materialization.series_index import inject_series_index
from products.endpoints.backend.materialization.transformer import (
    MaterializationTransformer,
    MaterializedColumn,
    transform_query_for_materialization,
    transform_select_for_materialized_table,
)
from products.endpoints.backend.materialization.types import (
    SUPPORTED_MATERIALIZATION_OPS,
    MaterializableVariable,
    Rejection,
    RejectionCode,
    VariableInHavingClauseError,
    VariableUsageInWhere,
)
from products.endpoints.backend.materialization.variables import (
    VariableInWhereFinder,
    VariablePlaceholderFinder,
    find_all_variable_usages,
    find_variable_in_where,
)

__all__ = [
    # aggregates
    "REAGGREGATABLE_BASE_FUNCTIONS",
    "AggregateReaggregation",
    "extract_aggregate_name",
    "get_reaggregation",
    # analyzer
    "analyze_variables_for_materialization",
    # cte_propagation
    "DownstreamCTEPlan",
    "DownstreamCTEShape",
    # insight_conversion
    "convert_insight_query_to_hogql",
    # range_buckets
    "SUPPORTED_BUCKET_FUNCTIONS",
    # series_index
    "inject_series_index",
    # transformer
    "MaterializationTransformer",
    "MaterializedColumn",
    "transform_query_for_materialization",
    "transform_select_for_materialized_table",
    # types
    "SUPPORTED_MATERIALIZATION_OPS",
    "MaterializableVariable",
    "Rejection",
    "RejectionCode",
    "VariableInHavingClauseError",
    "VariableUsageInWhere",
    # variables
    "VariableInWhereFinder",
    "VariablePlaceholderFinder",
    "find_all_variable_usages",
    "find_variable_in_where",
]
