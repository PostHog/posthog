from __future__ import annotations

import builtins
import dataclasses
from typing import TYPE_CHECKING

from posthog.schema import HogQLVariable

from posthog.hogql import ast

from posthog.models.insight_variable import InsightVariable

if TYPE_CHECKING:
    from posthog.schema import DashboardFilter

    from posthog.models.team import Team

    from products.endpoints.backend.models import EndpointVersion


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers (moved from api.py and openapi.py)
# ──────────────────────────────────────────────────────────────────────────────


def _get_single_breakdown_property(breakdown_filter: dict) -> str | None:
    """Extract the breakdown property name from either legacy or new format.

    Legacy: {"breakdown": "$browser", "breakdown_type": "event"}
    New:    {"breakdowns": [{"property": "$browser", "type": "event"}]}
    """
    breakdown = breakdown_filter.get("breakdown")
    if breakdown:
        return breakdown

    breakdowns = breakdown_filter.get("breakdowns") or []
    if len(breakdowns) == 1:
        return breakdowns[0].get("property")

    return None


def _get_single_breakdown_info(breakdown_filter: dict) -> tuple[str, str] | None:
    """Extract the breakdown property name and type from either legacy or new format.

    Returns (property_name, property_type) or None if not found.
    """
    breakdown = breakdown_filter.get("breakdown")
    if breakdown:
        breakdown_type = breakdown_filter.get("breakdown_type", "event")
        return (breakdown, breakdown_type)

    breakdowns = breakdown_filter.get("breakdowns") or []
    if len(breakdowns) == 1:
        prop = breakdowns[0].get("property")
        prop_type = breakdowns[0].get("type", "event")
        if prop:
            return (prop, prop_type)

    return None


def _apply_where_filter(
    select_query: ast.SelectQuery,
    column: str,
    value: str,
    op: ast.CompareOperationOp = ast.CompareOperationOp.Eq,
    value_wrapper_fns: builtins.list[str] | None = None,
) -> None:
    """Add a comparison filter to WHERE clause."""
    right_expr: ast.Expr = ast.Constant(value=value)
    for fn in reversed(value_wrapper_fns or []):
        right_expr = ast.Call(name=fn, args=[right_expr])
    condition = ast.CompareOperation(
        left=ast.Field(chain=[column]),
        op=op,
        right=right_expr,
    )
    if select_query.where:
        select_query.where = ast.And(exprs=[select_query.where, condition])
    else:
        select_query.where = condition


def _variables_to_filters(variables: dict[str, str], breakdown_info: tuple[str, str] | None = None):
    """Convert insight magic variables to DashboardFilter."""
    from posthog.schema import DashboardFilter, PropertyOperator

    date_from = variables.get("date_from")
    date_to = variables.get("date_to")

    properties: builtins.list[dict] | None = None
    if breakdown_info:
        breakdown_prop, breakdown_type = breakdown_info
        if breakdown_prop in variables:
            breakdown_value = variables[breakdown_prop]
            properties = [
                {
                    "key": breakdown_prop,
                    "value": breakdown_value,
                    "type": breakdown_type if breakdown_type else "event",
                    "operator": PropertyOperator.EXACT,
                }
            ]

    if not date_from and not date_to and not properties:
        return None

    return DashboardFilter(date_from=date_from, date_to=date_to, properties=properties)


def _parse_variables(query: dict[str, dict], variables: dict[str, str]) -> builtins.list[HogQLVariable] | None:
    """Parse HogQL variables from request into HogQLVariable list."""
    from rest_framework.exceptions import ValidationError

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
            raise ValidationError(f"Variable '{request_variable_code_name}' not found in query")

        variables_override.append(
            HogQLVariable(
                variableId=variable_id,
                code_name=request_variable_code_name,
                value=request_variable_value,
                isNull=True if request_variable_value is None else None,
            )
        )
    return variables_override


# ──────────────────────────────────────────────────────────────────────────────
# OpenAPI type mapping (previously in openapi.py)
# ──────────────────────────────────────────────────────────────────────────────

INSIGHT_VARIABLE_TYPE_TO_OPENAPI: dict[str, dict] = {
    # Keys match InsightVariable.Type string values (TextChoices evaluates to the string at runtime)
    "String": {"type": "string"},
    "Number": {"type": "number"},
    "Boolean": {"type": "boolean"},
    "List": {"type": "array", "items": {"type": "string"}},
    "Date": {"type": "string", "format": "date"},
}


# ──────────────────────────────────────────────────────────────────────────────
# InlineOverrides DTO
# ──────────────────────────────────────────────────────────────────────────────


@dataclasses.dataclass
class InlineOverrides:
    """Resolved overrides to apply when executing inline (non-materialized) queries."""

    variables_override: builtins.list[HogQLVariable] | None = None
    filters_override: object | None = None  # DashboardFilter instance
    deprecation_headers: dict[str, str] | None = None


# ──────────────────────────────────────────────────────────────────────────────
# Base handler
# ──────────────────────────────────────────────────────────────────────────────


class QueryKindHandler:
    """Strategy base class for per-query-type behavior.

    Concrete subclasses override only the methods that differ for their type.
    Safe defaults are provided for everything.
    """

    SUPPORTS_BREAKDOWN: bool = False
    BREAKDOWN_COLUMN: str | None = None
    SUPPORTS_PAGINATION: bool = False
    ACCEPTS_FILTERS_OVERRIDE: bool = True

    def get_allowed_variables(self, query: dict, is_materialized: bool, version: EndpointVersion) -> builtins.set[str]:
        return set()

    def get_required_variables_for_materialized(self, query: dict, version: EndpointVersion) -> builtins.set[str]:
        return set()

    def resolve_inline_overrides(
        self,
        query: dict,
        data_variables: dict[str, str] | None,
        data_filters_override: object | None,
    ) -> InlineOverrides:
        return InlineOverrides()

    def build_breakdown_filter_condition(self, value: str) -> ast.Expr | None:
        return None

    def build_materialized_select_columns(
        self, query: dict, version: EndpointVersion, team: Team
    ) -> builtins.list[ast.Expr]:
        return [ast.Field(chain=["*"])]

    def get_original_limit(self, query: dict, version: EndpointVersion) -> int | None:
        return None

    def apply_materialized_variable_filters(
        self,
        select_query: ast.SelectQuery,
        query: dict,
        variables: dict[str, str],
        version: EndpointVersion,
    ) -> None:
        pass

    def apply_materialized_filters_override(
        self,
        select_query: ast.SelectQuery,
        query: dict,
        filters_override: DashboardFilter,
    ) -> dict[str, str] | None:
        return None

    def can_use_materialized(
        self, query: dict, version: EndpointVersion, request_variables: dict[str, str] | None
    ) -> bool:
        return True

    def validate_filters_override(self, query_kind: str) -> None:
        pass

    def get_openapi_variables_schema_properties(self, query: dict, is_materialized: bool, team_id: int) -> dict:
        if not is_materialized:
            return {
                "date_from": {
                    "type": "string",
                    "description": "Filter results from this date (ISO format or relative like '-7d')",
                    "example": "2024-01-01",
                },
                "date_to": {
                    "type": "string",
                    "description": "Filter results until this date (ISO format or relative like 'now')",
                    "example": "2024-01-31",
                },
            }
        return {}

    def can_materialize(self, query: dict) -> tuple[bool, str]:
        return True, ""


# ──────────────────────────────────────────────────────────────────────────────
# Insight base handler
# ──────────────────────────────────────────────────────────────────────────────


class InsightQueryHandler(QueryKindHandler):
    """Shared implementation for all insight query types."""

    ACCEPTS_FILTERS_OVERRIDE: bool = True

    _DEPRECATION_HEADERS: dict[str, str] = {
        "X-PostHog-Warn": "filters_override is deprecated. Use variables instead: https://posthog.com/docs/api/endpoints"
    }

    def get_allowed_variables(self, query: dict, is_materialized: bool, version: EndpointVersion) -> builtins.set[str]:
        allowed: builtins.set[str] = set()
        if self.SUPPORTS_BREAKDOWN:
            breakdown_filter = query.get("breakdownFilter") or {}
            breakdown = _get_single_breakdown_property(breakdown_filter)
            if breakdown:
                allowed.add(breakdown)
        if not is_materialized:
            allowed.update({"date_from", "date_to"})
        return allowed

    def get_required_variables_for_materialized(self, query: dict, version: EndpointVersion) -> builtins.set[str]:
        if self.SUPPORTS_BREAKDOWN:
            breakdown_filter = query.get("breakdownFilter") or {}
            prop = _get_single_breakdown_property(breakdown_filter)
            return {prop} if prop else set()
        return set()

    def resolve_inline_overrides(
        self,
        query: dict,
        data_variables: dict[str, str] | None,
        data_filters_override: object | None,
    ) -> InlineOverrides:
        if data_filters_override is not None:
            return InlineOverrides(
                filters_override=data_filters_override,
                deprecation_headers=self._DEPRECATION_HEADERS,
            )
        if data_variables:
            breakdown_filter = query.get("breakdownFilter") or {}
            breakdown_info = _get_single_breakdown_info(breakdown_filter)
            return InlineOverrides(filters_override=_variables_to_filters(data_variables, breakdown_info))
        return InlineOverrides()

    def apply_materialized_variable_filters(
        self,
        select_query: ast.SelectQuery,
        query: dict,
        variables: dict[str, str],
        version: EndpointVersion,
    ) -> None:
        if not self.SUPPORTS_BREAKDOWN:
            return
        breakdown_filter = query.get("breakdownFilter") or {}
        breakdown_prop = _get_single_breakdown_property(breakdown_filter)
        if breakdown_prop and breakdown_prop in variables:
            value = variables[breakdown_prop]
            condition = self.build_breakdown_filter_condition(value)
            if condition:
                if select_query.where:
                    select_query.where = ast.And(exprs=[select_query.where, condition])
                else:
                    select_query.where = condition

    def apply_materialized_filters_override(
        self,
        select_query: ast.SelectQuery,
        query: dict,
        filters_override: DashboardFilter,
    ) -> dict[str, str] | None:
        if filters_override.properties:
            for prop in filters_override.properties:
                if hasattr(prop, "key") and hasattr(prop, "value") and prop.value is not None:
                    value = prop.value[0] if isinstance(prop.value, builtins.list) else prop.value
                    condition = self.build_breakdown_filter_condition(str(value))
                    if condition:
                        if select_query.where:
                            select_query.where = ast.And(exprs=[select_query.where, condition])
                        else:
                            select_query.where = condition
                    break
        return self._DEPRECATION_HEADERS

    def can_use_materialized(
        self, query: dict, version: EndpointVersion, request_variables: dict[str, str] | None
    ) -> bool:
        if not request_variables:
            return True
        if not self.SUPPORTS_BREAKDOWN:
            return False
        breakdown_filter = query.get("breakdownFilter") or {}
        breakdown = _get_single_breakdown_property(breakdown_filter)
        if not breakdown:
            return False
        return set(request_variables.keys()).issubset({breakdown})

    def can_materialize(self, query: dict) -> tuple[bool, str]:
        if self.SUPPORTS_BREAKDOWN:
            breakdown_filter = query.get("breakdownFilter") or {}
            breakdowns = breakdown_filter.get("breakdowns") or []
            if len(breakdowns) > 1:
                return False, "Multiple breakdowns not supported for materialization"
        return True, ""

    def get_openapi_variables_schema_properties(self, query: dict, is_materialized: bool, team_id: int) -> dict:
        props: dict = {}
        if self.SUPPORTS_BREAKDOWN:
            breakdown_filter = query.get("breakdownFilter") or {}
            breakdown = _get_single_breakdown_property(breakdown_filter)
            if breakdown:
                props[breakdown] = {
                    "type": "string",
                    "description": f"Filter by {breakdown} breakdown value",
                    "example": "Chrome",
                }
        if not is_materialized:
            props["date_from"] = {
                "type": "string",
                "description": "Filter results from this date (ISO format or relative like '-7d')",
                "example": "2024-01-01",
            }
            props["date_to"] = {
                "type": "string",
                "description": "Filter results until this date (ISO format or relative like 'now')",
                "example": "2024-01-31",
            }
        return props


# ──────────────────────────────────────────────────────────────────────────────
# Concrete insight handlers
# ──────────────────────────────────────────────────────────────────────────────


class TrendsQueryHandler(InsightQueryHandler):
    SUPPORTS_BREAKDOWN = True
    BREAKDOWN_COLUMN = "breakdown_value"

    def build_breakdown_filter_condition(self, value: str) -> ast.Expr:
        return ast.Call(
            name="has",
            args=[ast.Field(chain=["breakdown_value"]), ast.Constant(value=value)],
        )


class FunnelsQueryHandler(InsightQueryHandler):
    SUPPORTS_BREAKDOWN = True
    BREAKDOWN_COLUMN = "final_prop"

    def build_breakdown_filter_condition(self, value: str) -> ast.Expr:
        return ast.Call(
            name="has",
            args=[ast.Field(chain=["final_prop"]), ast.Constant(value=value)],
        )


class RetentionQueryHandler(InsightQueryHandler):
    SUPPORTS_BREAKDOWN = True
    BREAKDOWN_COLUMN = "breakdown_value"

    def build_breakdown_filter_condition(self, value: str) -> ast.Expr:
        return ast.Call(
            name="has",
            args=[ast.Field(chain=["breakdown_value"]), ast.Constant(value=value)],
        )


class LifecycleQueryHandler(InsightQueryHandler):
    SUPPORTS_BREAKDOWN = False


class StickinessQueryHandler(InsightQueryHandler):
    SUPPORTS_BREAKDOWN = False


class PathsQueryHandler(InsightQueryHandler):
    SUPPORTS_BREAKDOWN = False


# ──────────────────────────────────────────────────────────────────────────────
# HogQL handler
# ──────────────────────────────────────────────────────────────────────────────


class HogQLQueryHandler(QueryKindHandler):
    SUPPORTS_BREAKDOWN = False
    SUPPORTS_PAGINATION = True
    ACCEPTS_FILTERS_OVERRIDE = False

    def validate_filters_override(self, query_kind: str) -> None:
        from rest_framework.exceptions import ValidationError

        raise ValidationError("filters_override is not allowed for HogQL endpoints. Use variables instead.")

    def get_allowed_variables(self, query: dict, is_materialized: bool, version: EndpointVersion) -> builtins.set[str]:
        variables = query.get("variables", {})
        if not variables:
            return set()
        return {v.get("code_name") for v in variables.values() if v.get("code_name")}

    def get_required_variables_for_materialized(self, query: dict, version: EndpointVersion) -> builtins.set[str]:
        from products.endpoints.backend.materialization import analyze_variables_for_materialization

        if not query.get("variables"):
            return set()
        try:
            can_materialize, _, variable_infos = analyze_variables_for_materialization(query)
            return {v.code_name for v in variable_infos} if can_materialize else set()
        except Exception:
            return set()

    def can_use_materialized(
        self, query: dict, version: EndpointVersion, request_variables: dict[str, str] | None
    ) -> bool:
        if not request_variables:
            return True
        if not query.get("variables"):
            return False
        from products.endpoints.backend.materialization import analyze_variables_for_materialization

        try:
            can_materialize, _, variable_infos = analyze_variables_for_materialization(query)
        except Exception:
            return False
        if not can_materialize:
            return False
        materialized_codes = {v.code_name for v in variable_infos}
        return set(request_variables.keys()).issubset(materialized_codes)

    def get_original_limit(self, query: dict, version: EndpointVersion) -> int | None:
        from posthog.hogql.parser import parse_select

        query_str = query.get("query")
        if not query_str:
            return None
        try:
            parsed = parse_select(query_str)
            if isinstance(parsed, ast.SelectQuery):
                return parsed.limit.value if isinstance(parsed.limit, ast.Constant) else None
        except Exception:
            pass
        return None

    def build_materialized_select_columns(
        self, query: dict, version: EndpointVersion, team: Team
    ) -> builtins.list[ast.Expr]:
        from posthog.hogql.parser import parse_select

        from products.endpoints.backend.materialization import transform_select_for_materialized_table

        query_str = query.get("query")
        if not query_str or not query.get("variables"):
            return [ast.Field(chain=["*"])]
        try:
            parsed = parse_select(query_str)
            if isinstance(parsed, ast.SelectQuery) and parsed.select:
                return transform_select_for_materialized_table(builtins.list(parsed.select), team)
        except Exception:
            pass
        return [ast.Field(chain=["*"])]

    def apply_materialized_variable_filters(
        self,
        select_query: ast.SelectQuery,
        query: dict,
        variables: dict[str, str],
        version: EndpointVersion,
    ) -> None:
        from products.endpoints.backend.materialization import analyze_variables_for_materialization

        try:
            can_materialize, _, variable_infos = analyze_variables_for_materialization(query)
        except Exception:
            return
        if not can_materialize:
            return
        for mat_var in variable_infos:
            var_value = variables.get(mat_var.code_name)
            if var_value is not None:
                _apply_where_filter(
                    select_query,
                    mat_var.code_name,
                    var_value,
                    op=mat_var.operator,
                    value_wrapper_fns=mat_var.value_wrapper_fns,
                )

    def resolve_inline_overrides(
        self,
        query: dict,
        data_variables: dict[str, str] | None,
        data_filters_override: object | None,
    ) -> InlineOverrides:
        if data_variables:
            return InlineOverrides(variables_override=_parse_variables(query, data_variables))
        return InlineOverrides()

    def can_materialize(self, query: dict) -> tuple[bool, str]:
        hogql_query = query.get("query")
        if not hogql_query or not isinstance(hogql_query, str):
            return False, "Query is empty or invalid."
        return True, ""

    def get_openapi_variables_schema_properties(self, query: dict, is_materialized: bool, team_id: int) -> dict:
        variables = query.get("variables", {})
        if not variables:
            return {}
        variable_ids = builtins.list(variables.keys())
        variable_types = {
            str(uid): vtype
            for uid, vtype in InsightVariable.objects.filter(team_id=team_id, id__in=variable_ids).values_list(
                "id", "type"
            )
        }
        props: dict = {}
        for var_id, var_data in variables.items():
            code_name = var_data.get("code_name", var_id)
            default_value = var_data.get("value")
            var_type = variable_types.get(var_id)
            type_schema = (
                INSIGHT_VARIABLE_TYPE_TO_OPENAPI.get(var_type, {"type": "string"}) if var_type else {"type": "string"}
            )
            props[code_name] = {**type_schema, "description": f"Variable: {code_name}"}
            if default_value is not None:
                props[code_name]["example"] = default_value
        return props


# ──────────────────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────────────────

_HANDLER_REGISTRY: dict[str, type[QueryKindHandler]] = {
    "HogQLQuery": HogQLQueryHandler,
    "TrendsQuery": TrendsQueryHandler,
    "FunnelsQuery": FunnelsQueryHandler,
    "RetentionQuery": RetentionQueryHandler,
    "LifecycleQuery": LifecycleQueryHandler,
    "StickinessQuery": StickinessQueryHandler,
    "PathsQuery": PathsQueryHandler,
}

_HANDLER_INSTANCES: dict[str, QueryKindHandler] = {}


def get_query_handler(query_kind: str | None) -> QueryKindHandler:
    """Return the singleton handler for query_kind.

    Raises ValueError for unknown kinds so callers get a clear error
    rather than silent fallthrough.
    """
    if query_kind not in _HANDLER_REGISTRY:
        raise ValueError(f"Unknown query kind: {query_kind!r}")
    if query_kind not in _HANDLER_INSTANCES:
        _HANDLER_INSTANCES[query_kind] = _HANDLER_REGISTRY[query_kind]()
    return _HANDLER_INSTANCES[query_kind]
