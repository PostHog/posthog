"""Grafana template variables, resolved to the values that the dashboard JSON saved as current."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from typing import Any

import re2

from posthog.schema import MetricsDashboardVariable, MetricsDashboardVariableSelection, MetricsDashboardVariableSource

from products.metrics.backend.variable_options import re2_pattern
from products.metrics.backend.variables import (
    REFERENCE,
    VARIABLE_NAME,
    Substitution,
    Variable,
    reference_name,
    referenced_names,
    regex_escape,
    substitute_promql,
)

_SKIPPED_TYPES = frozenset({"datasource", "adhoc", "groupby"})
ALL_VALUE = "$__all"
_PROMQL_VARIABLE_QUERY = re.compile(r"^\s*(label_values|label_names|metrics|query_result)\s*\(", re.IGNORECASE)
# Macros such as $__rate_interval, which only resolve inside a panel.
_RANGE_MACRO = re.compile(r"\$\{?__|\[\[__")
# The limits of the variable options endpoint, so that each live variable can load its options.
MAX_NAME_LENGTH = 128
MAX_QUERY_LENGTH = 10_000
MAX_VALUE_LENGTH = 1024
MAX_VALUES = 1000
# Each change to a selection walks the variables that depend on it, so a dashboard keeps a practical number live.
MAX_LIVE_VARIABLES = 50
# An item holds `text : value`, so it can be longer than a value, but not much.
_MAX_CUSTOM_ITEM_LENGTH = 4 * MAX_VALUE_LENGTH
_CUSTOM_SEPARATOR = re.compile(r"\s:\s")
_REGEX_SYNTAX = re.compile(r"[\\^$.|?*+()\[\]{}]")
# Private use characters, which stand for variables while dependencies are checked.
_MARKER_START = 0xF0000
_MAX_MARKERS = 0xFFFD
# The datasources whose variable queries the PromQL options endpoint can run. None is the default datasource.
_PROMQL_DATASOURCES = frozenset({None, "prometheus"})


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


def _custom_items(query: str) -> list[str] | None:
    """The comma-separated items of a custom list, where `\\,` is a literal comma. None when the list is too large."""
    items: list[str] = []
    item_start = search_from = 0
    while True:
        comma = query.find(",", search_from)
        end = len(query) if comma < 0 else comma
        if end - item_start > _MAX_CUSTOM_ITEM_LENGTH or len(items) > MAX_VALUES:
            return None
        if comma > 0 and query[comma - 1] == "\\":
            search_from = comma + 1
            continue
        items.append(query[item_start:end])
        if comma < 0:
            return items
        item_start = search_from = comma + 1


def _custom_values(query: str) -> list[str] | None:
    """The values of a Grafana custom list. An item is `value` or `text : value`. None when the list is too large."""
    items = _custom_items(query)
    if items is None:
        return None
    values = []
    for item in items:
        text = item.replace("\\,", ",").strip()
        # Grafana splits `text : value` at the last separator that has text on both sides.
        separators = [match.start() for match in _CUSTOM_SEPARATOR.finditer(text) if 0 < match.start() < len(text) - 3]
        value = (text[separators[-1] + 3 :] if separators else text).strip()
        if value:
            values.append(value)
    return values


def _within_limits(values: list[str]) -> bool:
    return len(values) <= MAX_VALUES and all(len(value) <= MAX_VALUE_LENGTH for value in values)


def _runs_live(regex: str | None) -> bool:
    """Whether the options endpoint runs the regex as Grafana does."""
    if regex is None:
        return True
    # The options endpoint does not put variable values into the regex.
    if len(regex) > MAX_VALUE_LENGTH or referenced_names(regex):
        return False
    # The options endpoint takes one match per option, so a flag such as `g`, which Grafana uses to take every match,
    # changes the values.
    if regex.startswith("/") and regex.rfind("/") > 0 and set(regex[regex.rfind("/") + 1 :]) - set("ims"):
        return False
    try:
        pattern = re2.compile(re2_pattern(regex))
    except re2.error:
        return False
    # Grafana reads the `text` and `value` groups by name. The options endpoint takes the first group.
    return not pattern.groupindex


def _live_definition(
    name: str, kind: Any, item: dict[str, Any], variable: Variable, datasource_type: str | None
) -> MetricsDashboardVariable | None:
    """The dashboard variable that keeps a Grafana variable live. None when it cannot stay live."""
    if not VARIABLE_NAME.match(name) or variable.default_format is not None:
        return None
    if len(name) > MAX_NAME_LENGTH:
        return None
    custom_values: list[str] | None = None
    query: str | None = None
    all_value = variable.all_value
    # A live all value is regex text that gets the escapes of its string. Grafana's text already has the escapes of the
    # string it was written for, and with a backslash that differs between a quoted and a backtick string.
    if all_value is not None and "\\" in all_value:
        return None
    include_all = bool(item.get("includeAll"))
    if kind == "query":
        query = _query_text(item)
        if not _PROMQL_VARIABLE_QUERY.match(query) or _RANGE_MACRO.search(query) or len(query) > MAX_QUERY_LENGTH:
            return None
        # Grafana runs the regex in JavaScript, and the options endpoint runs it with RE2, which has no lookaround.
        if datasource_type not in _PROMQL_DATASOURCES or not _runs_live(_regex(item)):
            return None
        # A live All without an allValue matches every value, so it must not drop a filter that limits the options.
        if include_all and all_value is None and ("{" in query or _regex(item)):
            return None
        source = MetricsDashboardVariableSource.PROMQL
    elif kind == "custom":
        parsed = [] if variable.options else _custom_values(_query_text(item))
        if parsed is None:
            return None
        custom_values = list(variable.options) or parsed or list(variable.values)
        if not _within_limits(custom_values):
            return None
        if include_all and all_value is None:
            # Grafana matches only the listed values. A value with regex syntax would need escapes for each context.
            if not custom_values or any(regex_escape(value) != value for value in custom_values):
                return None
            all_value = f"({'|'.join(custom_values)})"
        source = MetricsDashboardVariableSource.CUSTOM
    elif kind in ("textbox", "constant"):
        source = MetricsDashboardVariableSource.TEXTBOX
    else:
        return None
    selected = list(variable.options if variable.is_all and not variable.values else variable.values)
    if not _within_limits(selected) or (all_value is not None and len(all_value) > MAX_VALUE_LENGTH):
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
        includeAll=include_all or None,
        allValue=all_value,
        current=MetricsDashboardVariableSelection(
            values=selected,
            all=variable.is_all or None,
        ),
    )


def _size_bound(variable: Variable) -> int:
    """The most characters that a reference to the variable becomes, with the regex alternation.

    A regex escape doubles a character, and the string escape doubles that backslash again, so `.` becomes `\\\\.`.
    """
    if variable.is_all and variable.all_value is not None:
        parts: tuple[str, ...] = (variable.all_value,)
    else:
        parts = variable.options if variable.is_all else variable.values
    return 4 * sum(len(part) for part in parts) + len(parts) + 2


def _in_loops(parents: dict[str, set[str]]) -> set[str]:
    """The variables in a loop of queries, which the dashboard cannot load in order."""

    def peel(edges: dict[str, set[str]]) -> set[str]:
        # Remove the variables that wait on nothing left, until only the loops and what they block stay.
        waiting = {name: len(names) for name, names in edges.items()}
        blocked: dict[str, list[str]] = {}
        for name, names in edges.items():
            for other in names:
                blocked.setdefault(other, []).append(name)
        ready = [name for name, count in waiting.items() if count == 0]
        while ready:
            for name in blocked.get(ready.pop(), ()):
                waiting[name] -= 1
                if waiting[name] == 0:
                    ready.append(name)
        return {name for name, count in waiting.items() if count > 0}

    after_loops = peel(parents)
    # The same pass over the reversed graph leaves out the variables that only depend on a loop.
    children: dict[str, set[str]] = {name: set() for name in after_loops}
    for name in after_loops:
        for parent in parents[name] & after_loops:
            children[parent].add(name)
    return peel(children)


def _resolvable(
    live: dict[str, MetricsDashboardVariable], variables: dict[str, Variable]
) -> dict[str, MetricsDashboardVariable]:
    """The live variables whose queries refer only to live variables or to variables with a saved value.

    A query that the saved values of static variables would make longer than the options API accepts is static too,
    and so is a variable in a loop of queries.
    """
    valued = [name for name, variable in variables.items() if variable.values or variable.is_all]
    if len(valued) > _MAX_MARKERS:
        return {}
    # Each variable with a value becomes one marker character, so a query is inspected without its saved values.
    markers = {chr(_MARKER_START + index): name for index, name in enumerate(valued)}
    stand_ins = {
        name: Variable(values=(marker,), is_all=False, all_value=None, options=()) for marker, name in markers.items()
    }
    hard: dict[str, list[str]] = {}
    soft: dict[str, list[str]] = {}
    references: dict[str, Counter[str]] = {}
    size: dict[str, int] = {}
    bounds = {name: _size_bound(variable) for name, variable in variables.items()}
    static: list[str] = []
    parents: dict[str, set[str]] = {}
    for name, definition in live.items():
        substitution = substitute_promql(definition.query or "", stand_ins)
        references[name] = Counter(markers[char] for char in substitution.text if char in markers)
        parents[name] = {other for other in [*substitution.unresolved, *references[name]] if other in live}
        size[name] = len(definition.query or "") + sum(
            count * bounds[other] for other, count in references[name].items() if other not in live
        )
        if any(other not in live for other in substitution.unresolved) or size[name] > MAX_QUERY_LENGTH:
            static.append(name)
        for other in substitution.unresolved:
            hard.setdefault(other, []).append(name)
        for other in references[name]:
            if other in live:
                soft.setdefault(other, []).append(name)
    static.extend(_in_loops(parents))
    # Each variable becomes static at most once, so the work grows with the number of references.
    removed: set[str] = set()
    while static:
        name = static.pop()
        if name in removed:
            continue
        removed.add(name)
        static.extend(hard.get(name, ()))
        # A variable that becomes static puts its saved values into the queries that refer to it.
        for dependent in soft.get(name, ()):
            size[dependent] += references[dependent][name] * bounds[name]
            if size[dependent] > MAX_QUERY_LENGTH:
                static.append(dependent)
    return {name: definition for name, definition in live.items() if name not in removed}


class TemplateVariables:
    def __init__(self, variables: dict[str, Variable], live: dict[str, MetricsDashboardVariable] | None = None) -> None:
        self._variables = variables
        self._live = live or {}

    @classmethod
    def from_templating(
        cls, items: Any, datasource_type: Callable[[Any], str | None] = lambda _: None
    ) -> TemplateVariables:
        """`datasource_type` gives the type of a Grafana datasource reference, or None when it is unknown."""
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
            selected = tuple(value for value in values if value != ALL_VALUE)
            # Grafana puts the value of a text box into a regex matcher as it is, so it can hold a regex.
            as_written = kind in ("textbox", "constant") and any(_REGEX_SYNTAX.search(value) for value in selected)
            variable = Variable(
                values=selected,
                is_all=is_all,
                all_value=all_value or None,
                options=options,
                default_format="raw" if as_written else None,
                all_value_as_written=True,
            )
            variables[item["name"]] = variable
            # Checking a definition compiles its regex, so the variables past the cap are not checked.
            if len(live) < MAX_LIVE_VARIABLES:
                definition = _live_definition(
                    item["name"], kind, item, variable, datasource_type(item.get("datasource"))
                )
                if definition is not None:
                    live[item["name"]] = definition
        return cls(variables, _resolvable(live, variables))

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
        # A list set to All gets an alternation as its all value, which a format such as `csv` does not change.
        for match in REFERENCE.finditer(expr):
            name = reference_name(match)
            definition = self._live.get(name)
            formatted = match.group("braced_format") or match.group("bracketed_format")
            if formatted and definition is not None and definition.allValue != self._variables[name].all_value:
                return None
        substitution = substitute_promql(expr, self._variables, keep=self._live)
        return None if substitution.unresolved else substitution.text
