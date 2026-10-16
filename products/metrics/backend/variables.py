"""Grafana-style variables in metrics queries: `$name`, `${name}`, `${name:format}` and `[[name]]`.

A dashboard stores its variables and their selections in its filters. When a tile runs, the runner
copies the values of the variables that the tile refers to into `query.variables`, so the values
reach the cache key and the async worker. Each language then gets the values in its own way:

- PromQL text gets the values put in as text, regex-escaped inside `=~` and `!~` matchers.
- SQL gets each reference changed to a HogQL placeholder that holds an `ast.Constant` or an
  `ast.Tuple`, so a value never becomes SQL text.
- Builder filters get their value, and a regex op when a variable has more than one value.
"""

from __future__ import annotations

import re
import dataclasses
from collections.abc import Collection, Iterable, Mapping

from posthog.schema import (
    MetricsDashboardVariable,
    MetricsDashboardVariableSource,
    MetricsFilterOp,
    MetricsQueryFilter,
    MetricsVariableValue,
)

from posthog.hogql import ast

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
# The text before a reference that is inside the string of a PromQL regex matcher, `label=~"...`.
_IN_PROMQL_REGEX_MATCHER = re.compile(r"""[=!]~\s*(["'])(?:(?!\1)[^\\]|\\.)*\Z""")
_SQL_REFERENCE = re.compile(r"\$\{(?P<braced>[A-Za-z0-9_]+)(?::[A-Za-z0-9_]+)?\}|\$(?P<plain>[A-Za-z0-9_]+)")
MATCH_ALL = ".*"


@frozen
class Variable:
    values: tuple[str, ...]
    is_all: bool
    all_value: str | None
    # The options that All expands to when it has no all value. Empty means "match everything".
    options: tuple[str, ...]


@frozen
class Substitution:
    text: str
    unresolved: tuple[str, ...]


@frozen
class SqlSubstitution:
    sql: str
    placeholders: dict[str, ast.Expr]
    unresolved: tuple[str, ...]


@frozen
class FilterSubstitution:
    # None when the filter matches everything, so the query drops it.
    filter: MetricsQueryFilter | None
    unresolved: tuple[str, ...]


@frozen
class FiltersSubstitution:
    filters: list[MetricsQueryFilter]
    unresolved: tuple[str, ...]


def reference_name(match: re.Match[str]) -> str:
    return match.group("braced") or match.group("bracketed") or match.group("plain")


def _is_variable_reference(name: str) -> bool:
    # A numeric reference such as $1 is a regex group in label_replace, not a variable.
    return name not in RANGE_VARIABLES and not name.isdigit()


def referenced_names(text: str | None) -> list[str]:
    names = (reference_name(match) for match in REFERENCE.finditer(text or ""))
    return list(dict.fromkeys(name for name in names if _is_variable_reference(name)))


def sql_referenced_names(sql: str | None) -> list[str]:
    """The variables a SQL query refers to. `[[name]]` is not a SQL reference, because `[[x]]` is a nested array."""
    names = (match.group("braced") or match.group("plain") for match in _SQL_REFERENCE.finditer(sql or ""))
    return list(dict.fromkeys(name for name in names if _is_variable_reference(name)))


def filter_referenced_names(filters: Iterable[MetricsQueryFilter] | None) -> list[str]:
    return list(
        dict.fromkeys(name for metric_filter in filters or () for name in referenced_names(metric_filter.value))
    )


def regex_escape(value: str) -> str:
    return "".join(f"\\{char}" if char in _REGEX_SPECIAL else char for char in value)


def promql_string_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def promql_regex_escape(value: str) -> str:
    # The value lands inside a double-quoted PromQL string, so each regex escape needs a doubled backslash.
    return promql_string_escape(regex_escape(value))


def _has_value(variable: Variable | None) -> bool:
    return variable is not None and (bool(variable.values) or variable.is_all)


def from_dashboard(definitions: Iterable[MetricsDashboardVariable] | None) -> dict[str, Variable]:
    """The current selection of each dashboard variable. A variable with no selection is left out."""
    variables: dict[str, Variable] = {}
    for definition in definitions or ():
        current = definition.current
        if current is None:
            continue
        variable = Variable(
            values=tuple(str(value) for value in current.values),
            is_all=bool(current.all) and bool(definition.includeAll),
            all_value=definition.allValue or None,
            options=(),
        )
        if _has_value(variable):
            variables[definition.name] = variable
    return variables


def from_query(values: Mapping[str, MetricsVariableValue] | None) -> dict[str, Variable]:
    """The variables that a dashboard set on a metrics query."""
    return {
        name: Variable(values=tuple(value.values), is_all=bool(value.all), all_value=value.allValue or None, options=())
        for name, value in (values or {}).items()
    }


def to_query(
    variables: Mapping[str, Variable],
    names: Iterable[str],
    definitions: Mapping[str, MetricsDashboardVariable] | None = None,
) -> dict[str, MetricsVariableValue]:
    """The values to set on a metrics query: only the variables it refers to, so the others do not reach its cache key.

    `definitions` are the variables whose All options the query loads when it runs.
    """
    return {
        name: MetricsVariableValue(
            values=list(variable.values),
            all=variable.is_all or None,
            allValue=variable.all_value,
            definition=(definitions or {}).get(name),
        )
        for name in names
        if (variable := variables.get(name)) is not None
    }


def query_definitions(values: Mapping[str, MetricsVariableValue] | None) -> dict[str, MetricsDashboardVariable]:
    return {name: value.definition for name, value in (values or {}).items() if value.definition is not None}


def all_definitions(
    names: Iterable[str],
    variables: Mapping[str, Variable],
    definitions: Mapping[str, MetricsDashboardVariable],
) -> dict[str, MetricsDashboardVariable]:
    """The definitions that SQL needs to load the options of All: of the named variables, and of the
    variables that their SQL queries refer to."""
    needed: dict[str, MetricsDashboardVariable] = {}
    queue = list(names)
    while queue:
        name = queue.pop()
        variable = variables.get(name)
        definition = definitions.get(name)
        if name in needed or variable is None or not variable.is_all or variable.values or definition is None:
            continue
        # The options query needs no current selection or label.
        needed[name] = definition.model_copy(update={"current": None, "label": None})
        if definition.source == MetricsDashboardVariableSource.SQL:
            queue.extend(sql_referenced_names(definition.query))
    return needed


def with_values(variable: Variable, values: Iterable[str]) -> Variable:
    return dataclasses.replace(variable, values=tuple(values))


def format_promql(variable: Variable, value_format: str | None, *, in_regex: bool = False) -> str:
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
    if value_format == "regex" or in_regex or len(values) > 1:
        escaped = [promql_regex_escape(value) for value in values]
        return f"({'|'.join(escaped)})" if len(escaped) > 1 else escaped[0]
    return promql_string_escape(values[0])


def substitute_promql(expr: str, variables: Mapping[str, Variable], *, keep: Collection[str] = ()) -> Substitution:
    """Put the variable values in a PromQL expression. Also returns the names it could not resolve.

    References to the names in `keep` stay in the text.
    """
    unresolved: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = reference_name(match)
        if not _is_variable_reference(name) or name in keep:
            return match.group(0)
        variable = variables.get(name)
        if variable is None or not _has_value(variable):
            unresolved.append(name)
            return match.group(0)
        # In a regex matcher, a dot in a selected value such as an IP address must stay a dot.
        in_regex = bool(_IN_PROMQL_REGEX_MATCHER.search(expr, 0, match.start()))
        return format_promql(
            variable, match.group("braced_format") or match.group("bracketed_format"), in_regex=in_regex
        )

    return Substitution(text=REFERENCE.sub(replace, expr), unresolved=tuple(dict.fromkeys(unresolved)))


def _quoted_end(sql: str, start: int) -> int:
    """The index after the closing quote of the string or quoted identifier that starts at `start`."""
    quote = sql[start]
    index = start + 1
    while index < len(sql):
        char = sql[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            if sql.startswith(quote, index + 1):
                index += 2
                continue
            return index + 1
        index += 1
    return len(sql)


def _comment_end(sql: str, start: int) -> int | None:
    if sql.startswith("--", start):
        end = sql.find("\n", start)
        return len(sql) if end < 0 else end
    if sql.startswith("/*", start):
        end = sql.find("*/", start + 2)
        return len(sql) if end < 0 else end + 2
    return None


def _sql_placeholder(name: str, variable: Variable) -> ast.Expr:
    if variable.is_all and not variable.values:
        raise ValueError(f"${name} is set to All, but its values are not known. Select values for ${name}.")
    if len(variable.values) == 1 and not variable.is_all:
        return ast.Constant(value=variable.values[0])
    return ast.Tuple(exprs=[ast.Constant(value=value) for value in variable.values])


def substitute_sql(sql: str, variables: Mapping[str, Variable]) -> SqlSubstitution:
    """Change each variable reference in a SQL query to a HogQL placeholder that holds its value.

    One value becomes a string constant and more than one value, or All, becomes a tuple, so write
    `job = $job` or `job IN $job`. A string that holds only a reference (`'$job'`) is one value, as in
    Grafana. A reference inside a longer string is an error, because a value is never SQL text.
    """
    parts: list[str] = []
    placeholders: dict[str, ast.Expr] = {}
    unresolved: list[str] = []

    def placeholder(name: str) -> str:
        variable = variables.get(name)
        if variable is None or not _has_value(variable):
            unresolved.append(name)
            return f"${name}"
        key = f"metric_variable_{name}"
        placeholders[key] = _sql_placeholder(name, variable)
        return f"{{{key}}}"

    index = 0
    while index < len(sql):
        char = sql[index]
        if (comment_end := _comment_end(sql, index)) is not None:
            parts.append(sql[index:comment_end])
            index = comment_end
            continue
        if char in "'\"`":
            end = _quoted_end(sql, index)
            literal = sql[index:end]
            if char == "'":
                whole = _SQL_REFERENCE.fullmatch(literal[1:-1])
                names = [name for name in referenced_names(literal) if name in variables]
                if whole is not None and (whole.group("braced") or whole.group("plain")) in variables:
                    parts.append(placeholder(whole.group("braced") or whole.group("plain")))
                    index = end
                    continue
                if names:
                    raise ValueError(
                        f"${names[0]} is inside a string. Put it outside the quotes, "
                        f"for example concat('prefix-', ${names[0]})."
                    )
            parts.append(literal)
            index = end
            continue
        match = _SQL_REFERENCE.match(sql, index)
        previous = sql[index - 1] if index else ""
        # A reference after a dot or inside a name (properties.$browser) is a field, not a variable.
        if match is not None and not (previous.isalnum() or previous in "_.$"):
            name = match.group("braced") or match.group("plain")
            if _is_variable_reference(name):
                parts.append(placeholder(name))
                index = match.end()
                continue
        parts.append(char)
        index += 1

    return SqlSubstitution(sql="".join(parts), placeholders=placeholders, unresolved=tuple(dict.fromkeys(unresolved)))


def _anchored_alternation(values: Iterable[str]) -> str:
    return f"^(?:{'|'.join(regex_escape(value) for value in values)})$"


def substitute_filter(metric_filter: MetricsQueryFilter, variables: Mapping[str, Variable]) -> FilterSubstitution:
    """Put the variable values in one builder filter."""
    negated = metric_filter.op in (MetricsFilterOp.NEQ, MetricsFilterOp.NOT_REGEX)
    is_regex = metric_filter.op in (MetricsFilterOp.REGEX, MetricsFilterOp.NOT_REGEX)
    match = REFERENCE.fullmatch(metric_filter.value.strip())
    if match is not None and _is_variable_reference(reference_name(match)):
        name = reference_name(match)
        variable = variables.get(name)
        if variable is None or not _has_value(variable):
            return FilterSubstitution(filter=metric_filter, unresolved=(name,))
        regex_op = MetricsFilterOp.NOT_REGEX if negated else MetricsFilterOp.REGEX
        if variable.is_all:
            if variable.all_value is not None:
                return FilterSubstitution(
                    filter=metric_filter.model_copy(update={"op": regex_op, "value": variable.all_value}),
                    unresolved=(),
                )
            if not negated:
                return FilterSubstitution(filter=None, unresolved=())
            return FilterSubstitution(
                filter=metric_filter.model_copy(update={"op": regex_op, "value": MATCH_ALL}), unresolved=()
            )
        if len(variable.values) == 1 and not is_regex:
            return FilterSubstitution(
                filter=metric_filter.model_copy(update={"value": variable.values[0]}), unresolved=()
            )
        return FilterSubstitution(
            filter=metric_filter.model_copy(update={"op": regex_op, "value": _anchored_alternation(variable.values)}),
            unresolved=(),
        )

    unresolved: list[str] = []

    def replace(inner: re.Match[str]) -> str:
        name = reference_name(inner)
        if not _is_variable_reference(name):
            return inner.group(0)
        variable = variables.get(name)
        if variable is None or not _has_value(variable):
            unresolved.append(name)
            return inner.group(0)
        if is_regex and variable.is_all:
            return variable.all_value or MATCH_ALL
        if is_regex:
            return f"(?:{'|'.join(regex_escape(value) for value in variable.values)})"
        return ",".join(variable.values)

    value = REFERENCE.sub(replace, metric_filter.value)
    return FilterSubstitution(
        filter=metric_filter.model_copy(update={"value": value}), unresolved=tuple(dict.fromkeys(unresolved))
    )


def substitute_filters(
    filters: Iterable[MetricsQueryFilter] | None, variables: Mapping[str, Variable]
) -> FiltersSubstitution:
    kept: list[MetricsQueryFilter] = []
    unresolved: list[str] = []
    for metric_filter in filters or ():
        substitution = substitute_filter(metric_filter, variables)
        unresolved.extend(substitution.unresolved)
        if substitution.filter is not None:
            kept.append(substitution.filter)
    return FiltersSubstitution(filters=kept, unresolved=tuple(dict.fromkeys(unresolved)))


def unresolved_message(names: Iterable[str]) -> str:
    listed = ", ".join(f"${name}" for name in names)
    return (
        f"The query refers to {listed}, which has no value. "
        "Open it from a dashboard that defines the variable, or select a value."
    )
