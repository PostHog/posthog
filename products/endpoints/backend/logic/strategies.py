"""Query-kind strategies for endpoints.

Endpoints execute one of two families of queries, each with its own rules for
variables, materialized-table filtering, pagination, and response shaping:

- ``HogQLEndpointStrategy``: raw HogQL queries with ``{variables.x}`` placeholders.
- ``InsightEndpointStrategy``: insight queries (Trends/Funnels/...) where breakdown
  properties act as variables and responses need re-shaping after materialized reads.

Everything that branches on ``query["kind"]`` belongs here, behind the shared
``EndpointQueryStrategy`` interface, so the execution and materialization services
stay kind-agnostic.
"""

import abc
import dataclasses
from collections.abc import Iterator
from functools import cached_property
from typing import TYPE_CHECKING, ClassVar, Optional

import structlog
from asgiref.sync import async_to_sync
from rest_framework.exceptions import ValidationError

from posthog.schema import DashboardFilter, EndpointRunRequest, HogQLVariable, PropertyOperator

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer.hogql import HogQLPrinter
from posthog.hogql.visitor import CloningVisitor

from posthog.clickhouse.query_tagging import Product
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.insights.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL
from posthog.models.team import Team

from products.endpoints.backend.insight_transformers import transform_materialized_insight_response
from products.endpoints.backend.logic.pagination import EndpointPagination
from products.endpoints.backend.materialization_transforms import (
    ENDPOINT_BREAKDOWN_LIMIT,
    MaterializableVariable,
    analyze_variables_for_materialization,
    prepare_insight_query_for_endpoint,
    transform_select_for_materialized_table,
)
from products.endpoints.backend.models import Endpoint, EndpointVersion

if TYPE_CHECKING:
    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

logger = structlog.get_logger(__name__)

# Query types that support user-configurable breakdown filtering
BREAKDOWN_SUPPORTED_QUERY_TYPES: frozenset[str] = frozenset({"TrendsQuery", "RetentionQuery"})


# ---------------------------------------------------------------------------
# Shared AST helpers
# ---------------------------------------------------------------------------


def add_where_condition(select_query: ast.SelectQuery, condition: ast.Expr) -> None:
    """Append a condition to select_query.where with AND."""
    if select_query.where:
        select_query.where = ast.And(exprs=[select_query.where, condition])
    else:
        select_query.where = condition


def apply_where_filter(
    select_query: ast.SelectQuery,
    column: str,
    value: str,
    op: ast.CompareOperationOp = ast.CompareOperationOp.Eq,
    value_wrapper_fns: list[str] | None = None,
    bucket_fn: str | None = None,
) -> None:
    """Add a comparison filter to WHERE clause.

    When bucket_fn is set (range variables), wrap the filter value with the
    bucket function so the comparison matches the bucketed column values.
    """
    right_expr: ast.Expr = ast.Constant(value=value)
    for fn in reversed(value_wrapper_fns or []):
        right_expr = ast.Call(name=fn, args=[right_expr])
    if bucket_fn:
        right_expr = ast.Call(name=bucket_fn, args=[ast.Call(name="toDateTime", args=[right_expr])])
    condition = ast.CompareOperation(
        left=ast.Field(chain=[column]),
        op=op,
        right=right_expr,
    )
    add_where_condition(select_query, condition)


class PlaceholderPreservingPrinter(HogQLPrinter):
    """HogQL printer that preserves {placeholder} syntax instead of raising on unresolved placeholders."""

    def visit_placeholder(self, node: ast.Placeholder) -> str:
        if node.field is None:
            raise QueryError("You can not use placeholders here")
        return f"{{{node.field}}}"


# ---------------------------------------------------------------------------
# Breakdown helpers (insight queries)
# ---------------------------------------------------------------------------


def iter_breakdowns(breakdown_filter: dict) -> Iterator[tuple[str, str]]:
    """Yield (property_name, property_type) from legacy or new breakdown format.

    Legacy: {"breakdown": "$browser", "breakdown_type": "event"}
    New:    {"breakdowns": [{"property": "$browser", "type": "event"}]}
    """
    breakdown = breakdown_filter.get("breakdown")
    if breakdown:
        yield (breakdown, breakdown_filter.get("breakdown_type", "event"))
        return
    for b in breakdown_filter.get("breakdowns") or []:
        prop = b.get("property")
        if prop:
            yield (prop, b.get("type", "event"))


def get_breakdown_properties(breakdown_filter: dict) -> list[str]:
    """Extract all breakdown property names from either legacy or new format."""
    return [name for name, _ in iter_breakdowns(breakdown_filter)]


def get_breakdown_column_indices(breakdown_filter: dict) -> dict[str, int]:
    """Map breakdown property names to their 1-based index in the breakdown_value array.

    Single breakdown: {"$browser": 0}  (0 means use the whole array, not an index)
    Multiple breakdowns: {"$browser": 1, "$os": 2}
    """
    props = get_breakdown_properties(breakdown_filter)
    if len(props) <= 1:
        return {props[0]: 0} if props else {}
    return {prop: i + 1 for i, prop in enumerate(props)}


def get_breakdown_infos(breakdown_filter: dict) -> list[tuple[str, str]]:
    """Extract all breakdown (property_name, property_type) pairs."""
    return list(iter_breakdowns(breakdown_filter))


def build_breakdown_filter_condition(query_kind: str | None, value: str, array_index: int = 0) -> ast.Expr | None:
    """Build the appropriate WHERE condition for breakdown filtering based on query type.

    Different insight types store breakdowns in different columns:
    - TrendsQuery, RetentionQuery: `breakdown_value` Array column
    - LifecycleQuery: No breakdown support

    array_index controls how to access the breakdown column:
    - 0: single breakdown — use has() on the full array
    - 1+: multiple breakdowns — use equality on breakdown_value[N]
    """
    if query_kind not in BREAKDOWN_SUPPORTED_QUERY_TYPES:
        logger.warning(
            "Query type does not support breakdown filtering",
            query_kind=query_kind,
        )
        return None

    if array_index > 0:
        return ast.CompareOperation(
            left=ast.ArrayAccess(
                array=ast.Field(chain=["breakdown_value"]),
                property=ast.Constant(value=array_index),
            ),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value=value),
        )

    return ast.Call(
        name="has",
        args=[ast.Field(chain=["breakdown_value"]), ast.Constant(value=value)],
    )


# ---------------------------------------------------------------------------
# Breakdown sentinel cleaning (response post-processing)
# ---------------------------------------------------------------------------


def _value_contains_other(value: object, other_label: str) -> bool:
    """Check if a breakdown value contains the 'Other' sentinel."""
    if isinstance(value, str):
        return value == other_label
    if isinstance(value, list):
        return any(item == other_label for item in value if isinstance(item, str))
    return False


def _clean_sentinel_value(value: object, clean_empty_string: bool) -> object:
    """Clean breakdown sentinel strings (null and other) in a value or list of values."""
    if isinstance(value, str):
        if value == BREAKDOWN_NULL_STRING_LABEL or (clean_empty_string and value == ""):
            return None
        if value == BREAKDOWN_OTHER_STRING_LABEL:
            return "Other"
    elif isinstance(value, list):
        return [_clean_sentinel_value(item, clean_empty_string) for item in value]
    return value


def _clean_sentinel_label(label: object) -> object:
    """Clean a label string containing ::-joined breakdown parts."""
    if not isinstance(label, str):
        return label
    if BREAKDOWN_NULL_STRING_LABEL not in label and BREAKDOWN_OTHER_STRING_LABEL not in label:
        return label
    parts = label.split("::")
    cleaned = [
        "null" if p == BREAKDOWN_NULL_STRING_LABEL else "Other" if p == BREAKDOWN_OTHER_STRING_LABEL else p
        for p in parts
    ]
    return "::".join(cleaned)


def clean_breakdown_sentinels(result: dict, clean_empty_string: bool) -> bool:
    """Replace breakdown sentinel strings in API response results in-place.

    Handles both list-of-lists (materialized/HogQL) and list-of-dicts (inline insight).
    ``clean_empty_string`` additionally rewrites plain '' to null — that's how null
    breakdown values are stored in materialized insight tables, but it must NOT be
    applied to arbitrary HogQL results where '' is a legitimate value.

    Returns True if the "Other" sentinel was found — meaning the breakdown_limit
    was exceeded; the caller decides how to report that.
    """
    rows = result.get("results")
    if not rows:
        return False

    found_other = False
    columns = result.get("columns")
    if columns:
        # HogQL/materialized path: results are list[tuple] or list[list]
        indices = [i for i, col in enumerate(columns) if col == "breakdown_value"]
        if not indices:
            return False
        for row_idx, row in enumerate(rows):
            needs_clean = any(isinstance(row[i], (str, list)) or row[i] is None for i in indices)
            if not needs_clean:
                continue
            if not found_other:
                found_other = any(_value_contains_other(row[i], BREAKDOWN_OTHER_STRING_LABEL) for i in indices)
            row_list = list(row)
            for i in indices:
                row_list[i] = _clean_sentinel_value(row_list[i], clean_empty_string)
            rows[row_idx] = type(row)(row_list)
    elif isinstance(rows[0], dict):
        # Inline insight path: results are list[dict]
        for row in rows:
            if "breakdown_value" in row:
                if not found_other:
                    found_other = _value_contains_other(row["breakdown_value"], BREAKDOWN_OTHER_STRING_LABEL)
                row["breakdown_value"] = _clean_sentinel_value(row["breakdown_value"], clean_empty_string)
            if "label" in row:
                if not found_other and isinstance(row["label"], str):
                    found_other = BREAKDOWN_OTHER_STRING_LABEL in row["label"]
                row["label"] = _clean_sentinel_label(row["label"])

    return found_other


def _emit_breakdown_limit_signal(team: Team, endpoint: Endpoint) -> None:
    """Fire a Signal when the breakdown limit was exceeded ('Other' bucket in results).

    Fails silently — signal emission must never break the response.
    """
    from products.signals.backend.facade.api import emit_signal

    try:
        async_to_sync(emit_signal)(
            team=team,
            source_product="endpoints",
            source_type="endpoint_breakdown_limit_exceeded",
            source_id=f"{team.id}:{endpoint.name}",
            description=(
                f"Endpoint '{endpoint.name}' exceeded the breakdown limit ({ENDPOINT_BREAKDOWN_LIMIT}) — "
                f"an 'Other' bucket appeared in its results, so callers are seeing aggregated values "
                f"for the long tail instead of per-value rows. Consider a lower-cardinality breakdown "
                f"property or filtering the query.\nEndpoint path: {endpoint.endpoint_path}"
            ),
            weight=0.4,
            extra={
                "endpoint_name": endpoint.name,
                "breakdown_limit": ENDPOINT_BREAKDOWN_LIMIT,
            },
        )
    except Exception:
        logger.exception("Failed to emit breakdown-limit signal", endpoint_name=endpoint.name, team_id=team.id)


# ---------------------------------------------------------------------------
# Strategy interface
# ---------------------------------------------------------------------------

FILTERS_OVERRIDE_DEPRECATION_HEADERS = {
    "X-PostHog-Warn": "filters_override is deprecated. Use variables instead: https://posthog.com/docs/api/endpoints"
}


@dataclasses.dataclass(frozen=True)
class InlineExecutionPlan:
    """Overrides and response headers for executing the original query inline."""

    variables_override: list[HogQLVariable] | None = None
    filters_override: DashboardFilter | None = None
    deprecation_headers: dict[str, str] | None = None


class EndpointQueryStrategy(abc.ABC):
    """Kind-specific behavior for an endpoint version's query."""

    supports_pagination: ClassVar[bool] = False
    supports_ducklake: ClassVar[bool] = False

    def __init__(self, endpoint: Endpoint, version: EndpointVersion, team: Team):
        self.endpoint = endpoint
        self.version = version
        self.team = team
        self.query: dict = version.query

    @property
    def query_kind(self) -> str | None:
        return self.query.get("kind")

    # --- variables ---

    @abc.abstractmethod
    def allowed_variables(self, is_materialized: bool) -> set[str]:
        """The set of variable names callers may pass to /run."""

    @abc.abstractmethod
    def required_materialized_variables(self) -> set[str]:
        """Variables that MUST be provided when running against the materialized table.

        SECURITY: materialized tables contain rows for every variable value; omitting
        a variable would return unfiltered data.
        """

    @abc.abstractmethod
    def can_serve_variables_from_materialized(self, requested: set[str]) -> bool:
        """Whether all requested variables can be answered by the materialized table."""

    def materialized_filters_override_satisfies_required(self, data: EndpointRunRequest) -> bool:
        """Whether ``data.filters_override`` actually supplies the required materialized filter.

        Only the insight strategy honors filters_override; for any other strategy a
        filters_override never satisfies the required-variable check.
        """
        return False

    # --- materialized execution ---

    @abc.abstractmethod
    def build_materialized_select(
        self,
        table_name: str,
        variable_infos: list[MaterializableVariable] | None = None,
    ) -> tuple[ast.SelectQuery, int | None]:
        """Build the base SELECT against the materialized table.

        Returns (select_query, original_limit) — caller is responsible for pagination.
        """

    @abc.abstractmethod
    def apply_materialized_filters(
        self, select_query: ast.SelectQuery, data: EndpointRunRequest
    ) -> dict[str, str] | None:
        """Apply variable/filter WHERE conditions to the materialized SELECT.

        Returns deprecation headers to attach to the response, if any.
        """

    @abc.abstractmethod
    def transform_materialized_response(self, response_data: dict, saved_query: "DataWarehouseSavedQuery") -> None:
        """Re-shape a materialized read into the inline response format."""

    @abc.abstractmethod
    def clean_response_sentinels(self, response_data: dict) -> None:
        """Rewrite internal breakdown sentinel strings in the response, in place."""

    # --- inline execution ---

    def prepare_inline_query(self, query: dict) -> dict:
        """Adjust the stored query before inline execution. Default: unchanged."""
        return query

    @abc.abstractmethod
    def build_inline_plan(self, query: dict, data: EndpointRunRequest) -> InlineExecutionPlan:
        """Translate request variables/filters into query-runner overrides."""

    def apply_pagination(self, query: dict, limit: int, offset: int) -> tuple[dict, EndpointPagination]:
        """Apply LIMIT/OFFSET pagination to the inline query. Raises for unsupported kinds."""
        raise ValidationError(
            {"limit": f"Limit/offset parameters are only supported for HogQLQuery, not {self.query_kind}"}
        )


class HogQLEndpointStrategy(EndpointQueryStrategy):
    """Endpoints backed by a raw HogQL query with {variables.x} placeholders."""

    supports_pagination = True
    supports_ducklake = True

    @cached_property
    def materialized_variables(self) -> list[MaterializableVariable]:
        """The materializable variable infos for this query, or [] if not analyzable."""
        if not self.query or not self.query.get("variables"):
            return []

        try:
            can_materialize, _, variable_infos = analyze_variables_for_materialization(
                self.query, bucket_overrides=self.version.bucket_overrides
            )
            return variable_infos if can_materialize else []
        except Exception:
            logger.debug("Failed to analyze variables for materialization", exc_info=True)
            return []

    def allowed_variables(self, is_materialized: bool) -> set[str]:
        variables = self.query.get("variables", {})
        return {v.get("code_name") for v in variables.values() if v.get("code_name")} if variables else set()

    def required_materialized_variables(self) -> set[str]:
        return {v.code_name for v in self.materialized_variables}

    def can_serve_variables_from_materialized(self, requested: set[str]) -> bool:
        materialized_codes = {v.code_name for v in self.materialized_variables}
        if not materialized_codes:
            return False
        return requested.issubset(materialized_codes)

    def _parse_original_query(self) -> tuple[list | None, int | None, bool]:
        """Parse the original HogQL query and extract SELECT columns, LIMIT, and GROUP BY presence.

        Returns (materialized_columns, limit, has_group_by) where columns/limit may be None.
        materialized_columns is a list of MaterializedColumn with re-aggregation metadata.
        """
        query_str = self.query.get("query")
        if not query_str:
            return None, None, False

        try:
            parsed = parse_select(query_str)
            if isinstance(parsed, ast.SelectQuery):
                columns = (
                    transform_select_for_materialized_table(list(parsed.select), self.team) if parsed.select else None
                )
                limit = parsed.limit.value if isinstance(parsed.limit, ast.Constant) else None
                has_group_by = bool(parsed.group_by)
                return columns, limit, has_group_by
        except Exception:
            logger.debug("Failed to parse original HogQL query", exc_info=True)

        return None, None, False

    def build_materialized_select(
        self,
        table_name: str,
        variable_infos: list[MaterializableVariable] | None = None,
    ) -> tuple[ast.SelectQuery, int | None]:
        """Build the base SELECT query against a materialized table.

        Wraps aggregate columns with their reaggregate_fn (e.g. sum("count()"))
        when needed to preserve SQL semantics. This happens in two cases:

        1. Range variables (bucket_fn != None): multiple materialized rows must
           be collapsed back into one aggregate per group.
        2. No GROUP BY + all-aggregate SELECT: without wrapping, an empty WHERE
           match returns 0 rows instead of the expected 1-row identity result
           (count→0, sum→0, min/max→type default). Wrapping restores the implicit
           single-group aggregate that SQL guarantees.

        Non-aggregate columns (GROUP BY dimensions) are passed through as-is and
        added to the GROUP BY clause.
        """
        select_columns: list[ast.Expr] = [ast.Field(chain=["*"])]
        group_by_columns: list[ast.Expr] = []

        original_select, original_limit, has_group_by = self._parse_original_query()
        mat_vars = variable_infos if variable_infos is not None else self.materialized_variables
        if mat_vars and original_select:
            has_range_vars = any(v.bucket_fn is not None for v in mat_vars)
            all_aggregates = all(col.is_aggregate and col.reaggregate_fn for col in original_select)
            needs_reaggregation = has_range_vars or (not has_group_by and all_aggregates)

            if needs_reaggregation:
                reagg_select: list[ast.Expr] = []
                for col in original_select:
                    if col.is_aggregate and col.reaggregate_fn:
                        reagg_select.append(ast.Call(name=col.reaggregate_fn, args=[col.expr]))
                    else:
                        reagg_select.append(col.expr)
                        if not col.is_aggregate:
                            group_by_columns.append(col.expr)
                select_columns = reagg_select
            else:
                select_columns = [col.expr for col in original_select]

        select_query = ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        )

        if group_by_columns:
            select_query.group_by = [CloningVisitor().visit(c) for c in group_by_columns]

        if original_limit is not None:
            select_query.limit = ast.Constant(value=original_limit)

        return select_query, original_limit

    def transform_materialized_response(self, response_data: dict, saved_query: "DataWarehouseSavedQuery") -> None:
        """HogQL materialized rows are flat and returned as-is — no re-shaping needed."""
        return None

    def clean_response_sentinels(self, response_data: dict) -> None:
        """Clean sentinel literals only — plain '' is a legitimate HogQL value and stays."""
        clean_breakdown_sentinels(response_data, clean_empty_string=False)

    def apply_materialized_filters(
        self, select_query: ast.SelectQuery, data: EndpointRunRequest
    ) -> dict[str, str] | None:
        if not data.variables:
            return None
        for mat_var in self.materialized_variables:
            var_value = data.variables.get(mat_var.code_name)
            if var_value is not None:
                apply_where_filter(
                    select_query,
                    mat_var.code_name,
                    var_value,
                    op=mat_var.operator,
                    value_wrapper_fns=mat_var.value_wrapper_fns,
                    bucket_fn=mat_var.bucket_fn,
                )
        return None

    def build_inline_plan(self, query: dict, data: EndpointRunRequest) -> InlineExecutionPlan:
        if not data.variables:
            return InlineExecutionPlan()
        return InlineExecutionPlan(variables_override=self._parse_variables(query, data.variables))

    def _parse_variables(self, query: dict, variables: dict[str, str]) -> list[HogQLVariable] | None:
        query_variables = query.get("variables", None)
        if not query_variables:
            return None

        variables_override = []
        for request_variable_code_name, request_variable_value in variables.items():
            variable_id = None
            for query_variable_id, query_variable_value in query_variables.items():
                if query_variable_value.get("code_name", None) == request_variable_code_name:
                    variable_id = query_variable_id

            if variable_id is None:
                raise ValidationError({"variables": f"Variable '{request_variable_code_name}' not found in query"})

            variables_override.append(
                HogQLVariable(
                    variableId=variable_id,
                    code_name=request_variable_code_name,
                    value=request_variable_value,
                    isNull=True if request_variable_value is None else None,
                )
            )
        return variables_override

    def apply_pagination(self, query: dict, limit: int, offset: int) -> tuple[dict, EndpointPagination]:
        """Apply pagination to a HogQL query.

        Parses the HogQL AST, applies LIMIT/OFFSET, and reprints using a
        placeholder-preserving printer so unresolved {variables.*} survive.
        """
        query_sql = query.get("query", "")
        parsed = parse_select(query_sql)
        if not isinstance(parsed, ast.SelectQuery):
            raise ValidationError(
                "Pagination is not supported for UNION queries. Wrap the UNION in a subquery: SELECT * FROM (... UNION ALL ...) LIMIT n"
            )

        ceiling = parsed.limit.value if isinstance(parsed.limit, ast.Constant) else None
        pagination = EndpointPagination(limit=limit, offset=offset, ceiling=ceiling)

        pagination.apply_to(parsed)

        ctx = HogQLContext(enable_select_queries=True, limit_top_select=False)
        query = query.copy()
        query["query"] = PlaceholderPreservingPrinter(context=ctx).visit(parsed)
        return query, pagination


class InsightEndpointStrategy(EndpointQueryStrategy):
    """Endpoints backed by an insight query (Trends/Lifecycle/Retention/...).

    Breakdown properties act as variables; `filters_override` is the deprecated
    way to provide them. Materialized reads need re-shaping into the inline
    insight response format.
    """

    BREAKDOWN_SUPPORTED_QUERY_TYPES: ClassVar[frozenset[str]] = BREAKDOWN_SUPPORTED_QUERY_TYPES
    # Query types with a materialized-response transformer
    INSIGHT_TRANSFORM_TYPES: ClassVar[set[str]] = {"TrendsQuery", "LifecycleQuery", "RetentionQuery"}

    @property
    def _breakdown_filter(self) -> dict:
        return self.query.get("breakdownFilter") or {}

    def allowed_variables(self, is_materialized: bool) -> set[str]:
        allowed: set[str] = set()

        # Only allow breakdown properties for query types that support it
        if self.query_kind in self.BREAKDOWN_SUPPORTED_QUERY_TYPES:
            allowed.update(get_breakdown_properties(self._breakdown_filter))

        if not is_materialized:
            # Non-materialized also allows date_from/date_to via filters_override
            allowed.update({"date_from", "date_to"})

        return allowed

    def required_materialized_variables(self) -> set[str]:
        if self.query_kind in self.BREAKDOWN_SUPPORTED_QUERY_TYPES:
            return set(get_breakdown_properties(self._breakdown_filter))
        return set()

    def can_serve_variables_from_materialized(self, requested: set[str]) -> bool:
        allowed_props = set(get_breakdown_properties(self._breakdown_filter))
        if not allowed_props:
            return False
        return requested.issubset(allowed_props)

    def materialized_filters_override_satisfies_required(self, data: EndpointRunRequest) -> bool:
        # apply_materialized_filters applies only the first property's value as a single breakdown
        # filter, so filters_override can only satisfy a single-breakdown endpoint. A multi-breakdown
        # endpoint would leave the other breakdowns unfiltered — require variables (one per breakdown).
        if len(self.required_materialized_variables()) != 1:
            return False
        fo = data.filters_override
        if not (fo and fo.properties):
            return False
        for prop in fo.properties:
            prop_value = getattr(prop, "value", None)
            if prop_value is not None:
                value = prop_value[0] if isinstance(prop_value, list) else prop_value
                return build_breakdown_filter_condition(self.query_kind, str(value)) is not None
        return False

    def build_materialized_select(
        self,
        table_name: str,
        variable_infos: list[MaterializableVariable] | None = None,
    ) -> tuple[ast.SelectQuery, int | None]:
        select_query = ast.SelectQuery(
            select=[ast.Field(chain=["*"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        )
        return select_query, None

    def apply_materialized_filters(
        self, select_query: ast.SelectQuery, data: EndpointRunRequest
    ) -> dict[str, str] | None:
        # filters_override takes precedence over variables (backwards compat)
        if data.filters_override is not None:
            if data.filters_override.properties:
                for prop in data.filters_override.properties:
                    if hasattr(prop, "key") and hasattr(prop, "value") and prop.value is not None:
                        # Convert value to string for breakdown filter
                        value = prop.value[0] if isinstance(prop.value, list) else prop.value
                        condition = build_breakdown_filter_condition(self.query_kind, str(value))
                        if condition:
                            add_where_condition(select_query, condition)
                        # filters_override is deprecated — only the first property is used
                        break
            return FILTERS_OVERRIDE_DEPRECATION_HEADERS

        if data.variables:
            index_mapping = get_breakdown_column_indices(self._breakdown_filter)
            for breakdown_prop, array_index in index_mapping.items():
                if breakdown_prop in data.variables:
                    condition = build_breakdown_filter_condition(
                        self.query_kind, data.variables[breakdown_prop], array_index=array_index
                    )
                    if condition:
                        add_where_condition(select_query, condition)
        return None

    def transform_materialized_response(self, response_data: dict, saved_query: "DataWarehouseSavedQuery") -> None:
        """Re-shape flat materialized rows into the inline insight response format.

        Raises MaterializedSeriesMismatchError on series drift (query edited after
        materialization) — the caller decides how to recover.
        """
        if self.query_kind not in self.INSIGHT_TRANSFORM_TYPES:
            return
        transform_materialized_insight_response(
            response_data,
            self.query,
            self.team,
            now=saved_query.last_run_at,
        )

    def clean_response_sentinels(self, response_data: dict) -> None:
        """Full cleaning: sentinel literals plus '' → null (how materialized insight
        tables store null breakdowns). An 'Other' bucket means the breakdown limit
        was exceeded — report it for visibility."""
        found_other = clean_breakdown_sentinels(response_data, clean_empty_string=True)
        if found_other:
            capture_exception(
                Exception(
                    f"Endpoint breakdown limit ({ENDPOINT_BREAKDOWN_LIMIT}) exceeded — 'Other' bucket appeared in results"
                )
            )
            _emit_breakdown_limit_signal(self.team, self.endpoint)

    def prepare_inline_query(self, query: dict) -> dict:
        return prepare_insight_query_for_endpoint(query)

    def build_inline_plan(self, query: dict, data: EndpointRunRequest) -> InlineExecutionPlan:
        # filters_override takes precedence over variables (backwards compat)
        if data.filters_override is not None:
            return InlineExecutionPlan(
                filters_override=data.filters_override,
                deprecation_headers=FILTERS_OVERRIDE_DEPRECATION_HEADERS,
            )
        if data.variables:
            breakdown_infos = get_breakdown_infos(self._breakdown_filter)
            return InlineExecutionPlan(
                filters_override=self._variables_to_filters(data.variables, breakdown_infos=breakdown_infos)
            )
        return InlineExecutionPlan()

    def _variables_to_filters(
        self,
        variables: dict[str, str],
        breakdown_infos: list[tuple[str, str]] | None = None,
    ) -> Optional[DashboardFilter]:
        """Convert insight magic variables to DashboardFilter.

        Args:
            variables: Dict of variable name -> value from the request
            breakdown_infos: List of (property_name, property_type) for breakdown filtering
        """
        date_from = variables.get("date_from")
        date_to = variables.get("date_to")

        properties: list[dict] = []
        for prop_name, prop_type in breakdown_infos or []:
            if prop_name not in variables:
                continue
            value = variables[prop_name]
            # Any failure to build a filter for a breakdown variable must error the
            # request — silently skipping would return unfiltered data, which is a
            # data-leak (same principle that gates materialized endpoints on having
            # all variables present).
            try:
                if prop_type == "hogql":
                    # HogQLPropertyFilter.key is a full HogQL predicate and doesn't accept
                    # `operator` (HogQLPropertyFilter has extra="forbid"), so build a
                    # `<expr> = <value>` (or `isNull(<expr>)`) predicate to filter with.
                    key_expr = parse_expr(prop_name)
                    predicate_expr: ast.Expr
                    if value == "":
                        predicate_expr = ast.Call(name="isNull", args=[key_expr])
                    else:
                        predicate_expr = ast.CompareOperation(
                            left=key_expr,
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Constant(value=value),
                        )
                    properties.append({"key": predicate_expr.to_hogql(), "type": "hogql"})
                    continue
                if value == "":
                    # Empty string means "null/unset" — match events where the property is missing.
                    # This keeps inline execution consistent with the materialized path,
                    # where null breakdown values are stored as '' in S3.
                    properties.append(
                        {
                            "key": prop_name,
                            "type": prop_type if prop_type else "event",
                            "operator": PropertyOperator.IS_NOT_SET,
                        }
                    )
                else:
                    properties.append(
                        {
                            "key": prop_name,
                            "value": value,
                            "type": prop_type if prop_type else "event",
                            "operator": PropertyOperator.EXACT,
                        }
                    )
            except Exception as e:
                capture_exception(
                    e,
                    {
                        "product": Product.ENDPOINTS,
                        "team_id": self.team.pk,
                        "endpoint_name": self.endpoint.name,
                        "prop_name": prop_name,
                        "prop_type": prop_type,
                    },
                )
                raise ValidationError(
                    {"variables": f"Could not apply filter for breakdown variable '{prop_name}'"}
                ) from e

        if not date_from and not date_to and not properties:
            return None

        return DashboardFilter(date_from=date_from, date_to=date_to, properties=properties)


def strategy_for(endpoint: Endpoint, version: EndpointVersion, team: Team) -> EndpointQueryStrategy:
    """Pick the strategy for an endpoint version based on its query kind."""
    if version.query.get("kind") == "HogQLQuery":
        return HogQLEndpointStrategy(endpoint, version, team)
    return InsightEndpointStrategy(endpoint, version, team)
