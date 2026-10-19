"""Grafana-style variables in metrics queries: `$name`, `${name}`, `${name:format}` and `[[name]]`.

SQL gets HogQL placeholders that hold constants, so a value never becomes SQL text.
"""

from __future__ import annotations

import re
import dataclasses
from collections.abc import Collection, Iterable, Iterator, Mapping
from typing import Any

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
_PROMQL_CONTROL_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
_SQL_REFERENCE = re.compile(r"\$\{(?P<braced>[A-Za-z0-9_]+)(?::[A-Za-z0-9_]+)?\}|\$(?P<plain>[A-Za-z0-9_]+)")
MATCH_ALL = ".*"
_LINE_END = re.compile(r"[\r\n]")
_SQL_TIME_PLACEHOLDERS = {
    "__from": "date_from",
    "__to": "date_to",
    "__interval": "interval",
    "__interval_seconds": "interval_seconds",
}


@frozen
class Variable:
    values: tuple[str, ...]
    is_all: bool
    all_value: str | None
    # The options that All expands to when it has no all value. Empty means "match everything".
    options: tuple[str, ...]
    # Grafana puts an imported all value into the query as it is written, whatever string holds it.
    all_value_as_written: bool = False
    # True once All has the values of every option, which can be none.
    loaded: bool = False
    # The format of a reference that names none, such as `raw` for a Grafana text box that holds a regex.
    default_format: str | None = None


@frozen
class PromQLStringContext:
    # The quote of the PromQL string that holds the reference, or None outside a string.
    quote: str | None
    in_regex: bool
    # The replacement argument of label_replace, where `$name` is a named regex group.
    in_replacement: bool = False


@frozen
class Substitution:
    text: str
    unresolved: tuple[str, ...]


@frozen
class SqlSubstitution:
    sql: str
    placeholders: dict[str, ast.Expr]
    unresolved: tuple[str, ...]
    # References inside longer strings. They are an error when the variable has a value.
    in_strings: tuple[str, ...] = ()


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
    """The variables a SQL query refers to, outside comments. `[[x]]` is a nested array, not a reference."""
    substitution = substitute_sql(sql or "", {})
    return list(dict.fromkeys([*substitution.unresolved, *substitution.in_strings]))


def _is_sql_reference(name: str) -> bool:
    return name in _SQL_TIME_PLACEHOLDERS or _is_variable_reference(name)


def _backslashes_before(text: str, position: int) -> int:
    count = 0
    while position - count > 0 and text[position - count - 1] == "\\":
        count += 1
    return count


def _is_escaped(text: str, position: int) -> bool:
    return _backslashes_before(text, position) % 2 == 1


def _filter_references(metric_filter: MetricsQueryFilter) -> Iterator[re.Match[str]]:
    is_regex = metric_filter.op in (MetricsFilterOp.REGEX, MetricsFilterOp.NOT_REGEX)
    for match in REFERENCE.finditer(metric_filter.value):
        # In a regex, \$ is a literal dollar sign.
        if _is_variable_reference(reference_name(match)) and not (
            is_regex and _is_escaped(metric_filter.value, match.start())
        ):
            yield match


def filter_referenced_names(filters: Iterable[MetricsQueryFilter] | None) -> list[str]:
    return list(
        dict.fromkeys(
            reference_name(match) for metric_filter in filters or () for match in _filter_references(metric_filter)
        )
    )


def regex_escape(value: str) -> str:
    return "".join(f"\\{char}" if char in _REGEX_SPECIAL else char for char in value)


def promql_string_escape(value: str, quote: str | None = '"') -> str:
    if quote is None:
        return value
    if quote == "`":
        # A raw string has no escapes.
        if "`" in value:
            raise ValueError("A value inside a backtick string cannot hold a backtick.")
        return value
    escaped = value.replace("\\", "\\\\").replace(quote, f"\\{quote}")
    return "".join(_PROMQL_CONTROL_ESCAPES.get(char, char) for char in escaped)


@dataclasses.dataclass(frozen=False)
class _PromQLScanner:
    """Finds the string that holds each reference in one pass, because references come in order."""

    expr: str
    index: int = 0
    quote: str | None = None
    in_regex: bool = False
    in_replacement: bool = False
    # The open brackets, each as [bracket, the function name before a parenthesis, the argument index].
    groups: list[list[Any]] = dataclasses.field(default_factory=list)

    def _function_name(self) -> str:
        end = self.index
        while end > 0 and self.expr[end - 1].isspace():
            end -= 1
        start = end
        while start > 0 and (self.expr[start - 1].isalnum() or self.expr[start - 1] in "_:"):
            start -= 1
        return self.expr[start:end].lower()

    def context_at(self, position: int) -> PromQLStringContext | None:
        """None when the position is inside a `#` comment."""
        expr = self.expr
        while self.index < position:
            char = expr[self.index]
            if self.quote is not None:
                if char == "\\" and self.quote != "`":
                    self.index += 2
                    continue
                if char == self.quote:
                    self.quote = None
            elif char == "#":
                end = _LINE_END.search(expr, self.index)
                self.index = len(expr) if end is None else end.start()
                continue
            elif char in "({":
                self.groups.append([char, self._function_name() if char == "(" else "", 0])
            elif char in ")}":
                if self.groups and self.groups[-1][0] == ("(" if char == ")" else "{"):
                    self.groups.pop()
            elif char == ",":
                if self.groups:
                    self.groups[-1][2] += 1
            elif char in "\"'`":
                self.quote = char
                before = self.index - 1
                while before >= 0 and expr[before].isspace():
                    before -= 1
                call = self.groups[-1] if self.groups else None
                after_matcher = before >= 1 and expr[before] == "~" and expr[before - 1] in "=!"
                self.in_regex = after_matcher or call == ["(", "label_replace", 4]
                self.in_replacement = call == ["(", "label_replace", 2]
            self.index += 1
        if self.quote is None and self.index > position:
            return None
        return PromQLStringContext(
            quote=self.quote,
            in_regex=self.quote is not None and self.in_regex,
            in_replacement=self.quote is not None and self.in_replacement,
        )


def _has_value(variable: Variable | None) -> bool:
    return variable is not None and (bool(variable.values) or variable.is_all)


def from_dashboard(definitions: Iterable[MetricsDashboardVariable] | None) -> dict[str, Variable]:
    """A variable with no selection is left out."""
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
    return dataclasses.replace(variable, values=tuple(values), loaded=True)


def format_promql(variable: Variable, value_format: str | None, *, context: PromQLStringContext) -> str:
    if variable.is_all:
        if variable.all_value is not None:
            if variable.all_value_as_written:
                return variable.all_value
            return promql_string_escape(variable.all_value, context.quote)
        if not variable.options:
            return MATCH_ALL
        values = variable.options
        value_format = value_format or "regex"
    else:
        values = variable.values
    if value_format in ("raw", "text", "csv"):
        return promql_string_escape(",".join(values), context.quote)
    if value_format == "pipe":
        return promql_string_escape("|".join(values), context.quote)
    if value_format == "regex" or context.in_regex or len(values) > 1:
        escaped = [promql_string_escape(regex_escape(value), context.quote) for value in values]
        return f"({'|'.join(escaped)})" if len(escaped) > 1 else escaped[0]
    return promql_string_escape(values[0], context.quote)


def substitute_promql(expr: str, variables: Mapping[str, Variable], *, keep: Collection[str] = ()) -> Substitution:
    """References to the names in `keep` stay in the text."""
    unresolved: list[str] = []
    scanner = _PromQLScanner(expr)

    def replace(match: re.Match[str]) -> str:
        name = reference_name(match)
        if not _is_variable_reference(name) or name in keep:
            return match.group(0)
        context = scanner.context_at(match.start())
        if context is None:
            return match.group(0)
        # A regex reads `\$` as a literal dollar sign. A quoted string writes that backslash as `\\`.
        if context.in_regex:
            backslashes = _backslashes_before(expr, match.start())
            if (backslashes if context.quote == "`" else backslashes // 2) % 2 == 1:
                return match.group(0)
        variable = variables.get(name)
        if variable is None and context.in_replacement:
            return match.group(0)
        if variable is None or not _has_value(variable):
            unresolved.append(name)
            return match.group(0)
        # In a regex matcher, a dot in a selected value such as an IP address must stay a dot.
        value_format = match.group("braced_format") or match.group("bracketed_format") or variable.default_format
        return format_promql(variable, value_format, context=context)

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
    # HogQL reads `#` followed by a digit as a token, not as a comment.
    if sql.startswith(("--", "//"), start) or (sql.startswith("#", start) and not sql[start + 1 : start + 2].isdigit()):
        line_end = _LINE_END.search(sql, start)
        return len(sql) if line_end is None else line_end.start()
    if sql.startswith("/*", start):
        end = sql.find("*/", start + 2)
        return len(sql) if end < 0 else end + 2
    return None


def _sql_placeholder(name: str, variable: Variable) -> ast.Expr:
    if variable.is_all and not variable.values and not variable.loaded:
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
    in_strings: list[str] = []

    def placeholder(name: str) -> str:
        if name in _SQL_TIME_PLACEHOLDERS:
            return f"{{{_SQL_TIME_PLACEHOLDERS[name]}}}"
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
                if whole is None:
                    in_strings.extend(name for name in referenced_names(literal) if name not in _SQL_TIME_PLACEHOLDERS)
                names = [name for name in referenced_names(literal) if name in variables]
                # A string that holds only a reference is a variable, so a missing selection is reported.
                if whole is not None and _is_sql_reference(whole.group("braced") or whole.group("plain")):
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
            if _is_sql_reference(name):
                parts.append(placeholder(name))
                index = match.end()
                continue
        parts.append(char)
        index += 1

    return SqlSubstitution(
        sql="".join(parts),
        placeholders=placeholders,
        unresolved=tuple(dict.fromkeys(unresolved)),
        in_strings=tuple(dict.fromkeys(in_strings)),
    )


def _anchored_alternation(values: Iterable[str]) -> str:
    return f"^(?:{'|'.join(regex_escape(value) for value in values)})$"


def substitute_filter(metric_filter: MetricsQueryFilter, variables: Mapping[str, Variable]) -> FilterSubstitution:
    negated = metric_filter.op in (MetricsFilterOp.NEQ, MetricsFilterOp.NOT_REGEX)
    is_regex = metric_filter.op in (MetricsFilterOp.REGEX, MetricsFilterOp.NOT_REGEX)
    match = REFERENCE.fullmatch(metric_filter.value)
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
    parts: list[str] = []
    end = 0
    for inner in _filter_references(metric_filter):
        name = reference_name(inner)
        parts.append(metric_filter.value[end : inner.start()])
        end = inner.end()
        variable = variables.get(name)
        if variable is None or not _has_value(variable):
            unresolved.append(name)
            parts.append(inner.group(0))
        elif is_regex and variable.is_all:
            parts.append(variable.all_value or MATCH_ALL)
        elif is_regex:
            parts.append(f"(?:{'|'.join(regex_escape(value) for value in variable.values)})")
        else:
            parts.append(",".join(variable.values))
    value = "".join(parts) + metric_filter.value[end:]
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
