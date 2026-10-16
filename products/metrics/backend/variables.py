"""Grafana-style variables in metrics queries: `$name`, `${name}`, `${name:format}` and `[[name]]`.

PromQL text gets the values put in as text. SQL text gets escaped HogQL literals, so a value can
never change the structure of the query. Builder filters get their value, and their op when a variable
has more than one value.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from posthog.schema import MetricsDashboardVariable, MetricsFilterOp, MetricsQueryFilter

from posthog.hogql.escape_sql import escape_hogql_string

from posthog.dataclasses import frozen

REFERENCE = re.compile(
    r"\$\{(?P<braced>[A-Za-z0-9_]+)(?::(?P<braced_format>[A-Za-z0-9_]+))?\}"
    r"|\[\[(?P<bracketed>[A-Za-z0-9_]+)(?::(?P<bracketed_format>[A-Za-z0-9_]+))?\]\]"
    r"|\$(?P<plain>[A-Za-z0-9_]+)"
)
# The query step and the dashboard range fill these, so the substitution must leave them in place.
RANGE_VARIABLES = frozenset({"__rate_interval", "__interval", "__range", "__range_s", "__range_ms", "__auto"})
VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REGEX_SPECIAL = set("\\^$.|?*+()[]{}")
MATCH_ALL = ".*"


@frozen
class Variable:
    values: tuple[str, ...]
    is_all: bool
    all_value: str | None
    # The options that All expands to when it has no all value. Empty means "match everything".
    options: tuple[str, ...]


def reference_name(match: re.Match[str]) -> str:
    return match.group("braced") or match.group("bracketed") or match.group("plain")


def _is_variable_reference(name: str) -> bool:
    # A numeric reference such as $1 is a regex group in label_replace, not a variable.
    return name not in RANGE_VARIABLES and not name.isdigit()


def referenced_names(text: str) -> list[str]:
    names = (reference_name(match) for match in REFERENCE.finditer(text))
    return list(dict.fromkeys(name for name in names if _is_variable_reference(name)))


def regex_escape(value: str) -> str:
    return "".join(f"\\{char}" if char in _REGEX_SPECIAL else char for char in value)


def _promql_string_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def promql_regex_escape(value: str) -> str:
    # The value lands inside a double-quoted PromQL string, so each regex escape needs a doubled backslash.
    return _promql_string_escape(regex_escape(value))


def from_dashboard(definitions: Iterable[MetricsDashboardVariable] | None) -> dict[str, Variable]:
    """The current selection of each dashboard variable. A variable with no selection is left out."""
    variables: dict[str, Variable] = {}
    for definition in definitions or ():
        current = definition.current
        if current is None:
            continue
        is_all = bool(current.all) and bool(definition.includeAll)
        values = tuple(str(value) for value in current.values)
        if not values and not is_all:
            continue
        variables[definition.name] = Variable(
            values=values,
            is_all=is_all,
            all_value=definition.allValue or None,
            options=(),
        )
    return variables


def format_promql(variable: Variable, value_format: str | None) -> str:
    if variable.is_all:
        if variable.all_value is not None:
            return variable.all_value
        if not variable.options:
            return MATCH_ALL
        values = variable.options
        value_format = value_format or "regex"
    else:
        values = variable.values
    if value_format in ("raw", "text", "csv"):
        return ",".join(values)
    if value_format == "pipe":
        return "|".join(values)
    if value_format == "regex" or len(values) > 1:
        escaped = [promql_regex_escape(value) for value in values]
        return f"({'|'.join(escaped)})" if len(escaped) > 1 else escaped[0]
    return _promql_string_escape(values[0])


def substitute_promql(expr: str, variables: Mapping[str, Variable]) -> tuple[str, list[str]]:
    """Put the variable values in a PromQL expression. Also returns the names it could not resolve."""
    unresolved: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = reference_name(match)
        if not _is_variable_reference(name):
            return match.group(0)
        variable = variables.get(name)
        if variable is None or (not variable.values and not variable.is_all):
            unresolved.append(name)
            return match.group(0)
        return format_promql(variable, match.group("braced_format") or match.group("bracketed_format"))

    return REFERENCE.sub(replace, expr), list(dict.fromkeys(unresolved))


def _sql_reference(names: Iterable[str]) -> re.Pattern[str] | None:
    alternatives = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    if not alternatives:
        return None
    # A quoted reference ('$job') is one value, as in Grafana. A reference after a dot or inside a
    # name (properties.$browser) is a field, not a variable.
    return re.compile(
        rf"'\$(?P<quoted>{alternatives})'"
        rf"|(?<![\w.$])\$\{{(?P<braced>{alternatives})(?::[A-Za-z0-9_]+)?\}}"
        rf"|(?<![\w.$])\$(?P<plain>{alternatives})(?!\w)"
    )


def substitute_sql(sql: str, variables: Mapping[str, Variable]) -> str:
    """Change each variable reference in a SQL query to an escaped HogQL literal of its value.

    One value becomes a string and more than one value, or All, becomes a tuple, so write
    `job = $job` or `job IN $job`. A value is always a literal, never SQL text.
    """
    pattern = _sql_reference(variables)
    if pattern is None:
        return sql

    def replace(match: re.Match[str]) -> str:
        variable = variables[match.group("quoted") or match.group("braced") or match.group("plain")]
        values = variable.values if not variable.is_all or variable.values else variable.options
        if len(values) == 1 and not variable.is_all:
            return escape_hogql_string(values[0])
        return f"({', '.join(escape_hogql_string(value) for value in values)})" if values else "tuple()"

    return pattern.sub(replace, sql)


def _anchored_alternation(values: Iterable[str]) -> str:
    return f"^(?:{'|'.join(regex_escape(value) for value in values)})$"


def substitute_filter(
    metric_filter: MetricsQueryFilter, variables: Mapping[str, Variable]
) -> tuple[MetricsQueryFilter | None, list[str]]:
    """Put the variable values in one builder filter. Returns None when the filter matches everything."""
    match = REFERENCE.fullmatch(metric_filter.value.strip())
    if match is not None and _is_variable_reference(reference_name(match)):
        name = reference_name(match)
        variable = variables.get(name)
        if variable is None or (not variable.values and not variable.is_all):
            return metric_filter, [name]
        negated = metric_filter.op in (MetricsFilterOp.NEQ, MetricsFilterOp.NOT_REGEX)
        regex_op = MetricsFilterOp.NOT_REGEX if negated else MetricsFilterOp.REGEX
        if variable.is_all:
            if variable.all_value is not None:
                return metric_filter.model_copy(update={"op": regex_op, "value": variable.all_value}), []
            if not negated:
                return None, []
            return metric_filter.model_copy(update={"op": regex_op, "value": MATCH_ALL}), []
        if len(variable.values) == 1:
            return metric_filter.model_copy(update={"value": variable.values[0]}), []
        return metric_filter.model_copy(update={"op": regex_op, "value": _anchored_alternation(variable.values)}), []

    unresolved: list[str] = []
    is_regex = metric_filter.op in (MetricsFilterOp.REGEX, MetricsFilterOp.NOT_REGEX)

    def replace(inner: re.Match[str]) -> str:
        name = reference_name(inner)
        if not _is_variable_reference(name):
            return inner.group(0)
        variable = variables.get(name)
        if variable is None or (not variable.values and not variable.is_all):
            unresolved.append(name)
            return inner.group(0)
        if is_regex and variable.is_all:
            return variable.all_value or MATCH_ALL
        if is_regex:
            return f"(?:{'|'.join(regex_escape(value) for value in variable.values)})"
        return ",".join(variable.values)

    value = REFERENCE.sub(replace, metric_filter.value)
    return metric_filter.model_copy(update={"value": value}), list(dict.fromkeys(unresolved))


def substitute_filters(
    filters: Iterable[MetricsQueryFilter] | None, variables: Mapping[str, Variable]
) -> tuple[list[MetricsQueryFilter], list[str]]:
    kept: list[MetricsQueryFilter] = []
    unresolved: list[str] = []
    for metric_filter in filters or ():
        substituted, missing = substitute_filter(metric_filter, variables)
        unresolved.extend(missing)
        if substituted is not None:
            kept.append(substituted)
    return kept, list(dict.fromkeys(unresolved))


def unresolved_message(names: Iterable[str]) -> str:
    listed = ", ".join(f"${name}" for name in names)
    return (
        f"The query refers to {listed}, which has no value. "
        "Open it from a dashboard that defines the variable, or select a value."
    )
