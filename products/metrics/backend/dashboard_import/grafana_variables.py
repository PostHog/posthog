"""Grafana template variables, resolved to the values that the dashboard JSON saved as current."""

from __future__ import annotations

import re
from typing import Any

from posthog.schema import MetricsDashboardVariable, MetricsDashboardVariableSelection, MetricsDashboardVariableSource

from products.metrics.backend.variables import (
    VARIABLE_NAME,
    Substitution,
    Variable,
    referenced_names,
    substitute_promql,
)

_SKIPPED_TYPES = frozenset({"datasource", "adhoc", "groupby"})
ALL_VALUE = "$__all"
_PROMQL_VARIABLE_QUERY = re.compile(r"^\s*(label_values|label_names|metrics|query_result)\s*\(", re.IGNORECASE)


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value if item is not None)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return (str(value),)
    return ()


def _query_text(item: dict[str, Any]) -> str:
    query = item.get("query")
    if isinstance(query, dict):
        query = query.get("query")
    return query.strip() if isinstance(query, str) else ""


def _regex(item: dict[str, Any]) -> str | None:
    regex = item.get("regex")
    if not isinstance(regex, str) or not regex.strip():
        return None
    return regex.strip()


def _live_definition(name: str, kind: Any, item: dict[str, Any], variable: Variable) -> MetricsDashboardVariable | None:
    """The dashboard variable that keeps a Grafana variable live. None when it cannot stay live."""
    if not VARIABLE_NAME.match(name):
        return None
    custom_values: list[str] | None = None
    query: str | None = None
    if kind == "query":
        query = _query_text(item)
        if not _PROMQL_VARIABLE_QUERY.match(query):
            return None
        source = MetricsDashboardVariableSource.PROMQL
    elif kind == "custom":
        custom_values = (
            list(variable.options)
            or [part.strip() for part in _query_text(item).split(",") if part.strip()]
            or list(variable.values)
        )
        source = MetricsDashboardVariableSource.CUSTOM
    elif kind in ("textbox", "constant"):
        source = MetricsDashboardVariableSource.TEXTBOX
    else:
        return None
    label = item.get("label")
    return MetricsDashboardVariable(
        name=name,
        label=label if isinstance(label, str) and label else None,
        source=source,
        customValues=custom_values,
        query=query,
        regex=_regex(item) if kind == "query" else None,
        multi=bool(item.get("multi")) or None,
        includeAll=bool(item.get("includeAll")) or None,
        allValue=variable.all_value,
        current=MetricsDashboardVariableSelection(
            values=list(variable.options if variable.is_all and not variable.values else variable.values),
            all=variable.is_all or None,
        ),
    )


class TemplateVariables:
    def __init__(self, variables: dict[str, Variable], live: dict[str, MetricsDashboardVariable] | None = None) -> None:
        self._variables = variables
        self._live = live or {}

    @classmethod
    def from_templating(cls, items: Any) -> TemplateVariables:
        variables: dict[str, Variable] = {}
        live: dict[str, MetricsDashboardVariable] = {}
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            kind = item.get("type")
            if kind in _SKIPPED_TYPES:
                continue
            raw_current = item.get("current")
            current: dict[str, Any] = raw_current if isinstance(raw_current, dict) else {}
            values = _strings(current.get("value"))
            if not values and kind in ("constant", "textbox"):
                values = _strings(item.get("query"))
            if kind == "interval":
                # An "auto" interval resolves per panel in Grafana, which is the query step here.
                values = tuple("$__interval" if value.startswith("$__auto") else value for value in values)
            options = tuple(
                str(option.get("value"))
                for option in item.get("options") or []
                if isinstance(option, dict) and option.get("value") not in (None, ALL_VALUE)
            )
            all_value = item.get("allValue") if isinstance(item.get("allValue"), str) else None
            is_all = ALL_VALUE in values or (current.get("text") == "All" and bool(item.get("includeAll")))
            variable = Variable(
                values=tuple(value for value in values if value != ALL_VALUE),
                is_all=is_all,
                all_value=all_value or None,
                options=options,
            )
            variables[item["name"]] = variable
            if definition := _live_definition(item["name"], kind, item, variable):
                live[item["name"]] = definition
        return cls(variables, live)

    def summary(self) -> dict[str, str]:
        return {
            name: "All" if variable.is_all else ", ".join(variable.values) for name, variable in self._variables.items()
        }

    def definitions(self) -> list[MetricsDashboardVariable]:
        """The variables that the imported dashboard keeps live, in the Grafana order.

        A variable query keeps its references to live variables. The others, such as an interval,
        get their saved values, because the dashboard does not define them.
        """
        return [
            definition.model_copy(
                update={"query": substitute_promql(definition.query, self._variables, keep=self._live).text}
            )
            if definition.query
            else definition
            for definition in self._live.values()
        ]

    def substitute(self, expr: str) -> Substitution:
        """Replace variable references with their saved values. Also returns the names it could not resolve."""
        return substitute_promql(expr, self._variables)

    def template(self, expr: str) -> str | None:
        """Keep references to live variables and put in the saved values of the others.

        None when the expression refers to no live variable, or to a variable that has no saved value.
        """
        if not any(name in self._live for name in referenced_names(expr)):
            return None
        substitution = substitute_promql(expr, self._variables, keep=self._live)
        return None if substitution.unresolved else substitution.text
