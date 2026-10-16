"""The options of a metrics dashboard variable, from a static list or a PromQL or SQL query.

The query can refer to other variables, so a variable can depend on the selection of another one.
"""

from __future__ import annotations

import re
import datetime as dt
from collections.abc import Iterable, Mapping
from itertools import islice
from typing import Any

from posthog.schema import MetricsDashboardVariable, MetricsDashboardVariableSource

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.dataclasses import frozen
from posthog.models import Team

from products.metrics.backend.metric_query_runner import _QUERY_SETTINGS
from products.metrics.backend.promql import PromQLQueryError, snuffle_payload
from products.metrics.backend.sql_mode import run_metrics_sql_values
from products.metrics.backend.variables import (
    Variable,
    promql_string_escape,
    referenced_names,
    substitute_promql,
    substitute_sql,
    unresolved_message,
    with_values,
)

MAX_VARIABLE_OPTIONS = 1000
# All in a SQL variable query fills its values from the queries of other variables. This stops a loop.
_MAX_ALL_DEPTH = 5
_FUNCTION = re.compile(r"^\s*(?P<name>label_values|label_names|metrics|query_result)\s*\((?P<args>.*)\)\s*$", re.DOTALL)
_LABEL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@frozen
class LabelValuesArgs:
    selector: str
    label: str


def _label_values_args(args: str) -> LabelValuesArgs:
    """Split `selector, label` at the last comma outside brackets and quotes."""
    depth = 0
    quote: str | None = None
    split_at = -1
    index = 0
    while index < len(args):
        char = args[index]
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = None
        elif char in "\"'`":
            quote = char
        elif char in "({[":
            depth += 1
        elif char in ")}]":
            depth -= 1
        elif char == "," and depth == 0:
            split_at = index
        index += 1
    if split_at < 0:
        return LabelValuesArgs(selector="", label=args.strip())
    return LabelValuesArgs(selector=args[:split_at].strip(), label=args[split_at + 1 :].strip())


def _strings(data: object) -> list[str]:
    return [str(item) for item in islice(data, MAX_VARIABLE_OPTIONS)] if isinstance(data, list) else []


def _query_result_line(result: object) -> str | None:
    # Grafana shows each sample as `metric{label="value"} value timestamp`, and the regex reads from that text.
    if not isinstance(result, dict):
        return None
    labels = {str(key): str(value) for key, value in (result.get("metric") or {}).items()}
    name = labels.pop("__name__", "")
    sample = result.get("value")
    if not isinstance(sample, list) or len(sample) != 2:
        return None
    matchers = ", ".join(f'{key}="{value}"' for key, value in sorted(labels.items()))
    return f"{name}{{{matchers}}} {sample[1]} {int(float(sample[0]) * 1000)}"


def _promql_options(team: Team, query: str, date_from: dt.datetime, date_to: dt.datetime) -> list[str]:
    match = _FUNCTION.match(query)
    if match is None:
        raise PromQLQueryError(
            "Use label_values(label), label_values(selector, label), label_names(), metrics(regex) "
            "or query_result(expr) in a PromQL variable query."
        )
    name, args = match.group("name"), match.group("args").strip()
    # Snuffle stops at the limit, so a label with many values does not travel in full.
    params: dict[str, list[str]] = {
        "start": [str(date_from.timestamp())],
        "end": [str(date_to.timestamp())],
        "limit": [str(MAX_VARIABLE_OPTIONS)],
    }
    if name == "label_values":
        label_args = _label_values_args(args)
        if not _LABEL_NAME.match(label_args.label):
            raise PromQLQueryError(f'"{label_args.label}" is not a label name.')
        if label_args.selector:
            params["match[]"] = [label_args.selector]
        return _strings(
            snuffle_payload(team, "GET", f"/api/v1/label/{label_args.label}/values", params=params).get("data")
        )
    if name == "label_names":
        if args:
            params["match[]"] = [args]
        return _strings(snuffle_payload(team, "GET", "/api/v1/labels", params=params).get("data"))
    if name == "metrics":
        pattern = args.strip("\"'")
        if pattern:
            # Grafana matches the regex anywhere in the name. A PromQL matcher matches the whole name.
            params["match[]"] = [f'{{__name__=~".*(?:{promql_string_escape(pattern)}).*"}}']
        return _strings(snuffle_payload(team, "GET", "/api/v1/label/__name__/values", params=params).get("data"))
    if not args:
        raise PromQLQueryError("query_result needs a PromQL expression.")
    data = snuffle_payload(
        team, "POST", "/api/v1/query", data={"query": args, "time": params["end"][0], "limit": params["limit"][0]}
    ).get("data")
    results = data.get("result") if isinstance(data, dict) else None
    lines = (_query_result_line(result) for result in results or [])
    return list(islice((line for line in lines if line is not None), MAX_VARIABLE_OPTIONS))


def _has_capture_group(regex: str) -> bool:
    """Whether the pattern has a capturing group: an unescaped `(` outside a class, not followed by `?`."""
    in_class = False
    index = 0
    while index < len(regex):
        char = regex[index]
        if char == "\\":
            index += 2
            continue
        if in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif char == "(" and not regex.startswith("?", index + 1):
            return True
        index += 1
    return False


def apply_regex(team: Team, options: list[str], regex: str | None) -> list[str]:
    """Keep the options that match the variable's regex. With a capture group, the option is the first group.

    ClickHouse runs the pattern with RE2, so a user pattern cannot backtrack without end.
    """
    pattern = (regex or "").strip()
    if pattern.startswith("/") and pattern.rfind("/") > 0:
        pattern = pattern[1 : pattern.rfind("/")]
    if not pattern or not options:
        return options
    value = "extract(x, {pattern})" if _has_capture_group(pattern) else "x"
    query = parse_select(
        f"SELECT arrayDistinct(arrayMap(x -> {value}, arrayFilter(x -> match(x, {{pattern}}), {{options}})))",
        placeholders={
            "pattern": ast.Constant(value=pattern),
            "options": ast.Array(exprs=[ast.Constant(value=option) for option in options]),
        },
    )
    try:
        response = execute_hogql_query(
            query_type="MetricsVariableRegex", query=query, team=team, workload=Workload.LOGS, settings=_QUERY_SETTINGS
        )
    except ExposedHogQLError as exc:
        raise ValueError(f"The variable regex cannot be used: {exc}") from exc
    rows = response.results or []
    return [str(option) for option in rows[0][0]] if rows else []


def fill_all_values(
    *,
    team: Team,
    names: Iterable[str],
    variables: Mapping[str, Variable],
    definitions: Mapping[str, MetricsDashboardVariable],
    date_from: dt.datetime,
    date_to: dt.datetime,
    depth: int = 0,
) -> dict[str, Variable]:
    """Give each variable that is set to All the values of every option, for SQL, which cannot match everything.

    A dashboard does not store the options of All, so that its URL stays short. They come from the
    variable's own list or query.
    """
    filled = dict(variables)
    for name in names:
        variable = filled.get(name)
        definition = definitions.get(name)
        if variable is None or not variable.is_all or variable.values or definition is None:
            continue
        if depth >= _MAX_ALL_DEPTH:
            raise ValueError(f"The variable queries refer to each other in a loop through ${name}.")
        options = list_variable_options(
            team=team,
            source=definition.source,
            query=definition.query,
            custom_values=definition.customValues,
            variables=filled,
            definitions=definitions,
            date_from=date_from,
            date_to=date_to,
            depth=depth + 1,
        )
        filled[name] = with_values(variable, apply_regex(team, options, definition.regex))
    return filled


def list_variable_options(
    *,
    team: Team,
    source: MetricsDashboardVariableSource,
    query: str | None,
    custom_values: list[str] | None,
    variables: Mapping[str, Variable],
    date_from: dt.datetime,
    date_to: dt.datetime,
    definitions: Mapping[str, MetricsDashboardVariable] | None = None,
    depth: int = 0,
) -> list[str]:
    """The options of one variable, in the order the source gives them. Raises `ValueError` for a bad query.

    `definitions` lets a SQL query use another variable that is set to All, by loading its options.
    """
    options: list[Any]
    if source == MetricsDashboardVariableSource.CUSTOM:
        options = [value for value in custom_values or [] if value]
    elif source == MetricsDashboardVariableSource.TEXTBOX:
        options = []
    elif not (query or "").strip():
        raise ValueError("Write a query for the variable first.")
    elif source == MetricsDashboardVariableSource.PROMQL:
        substitution = substitute_promql(query or "", variables)
        if substitution.unresolved:
            raise ValueError(unresolved_message(substitution.unresolved))
        options = _promql_options(team, substitution.text, date_from, date_to)
    else:
        if definitions:
            variables = fill_all_values(
                team=team,
                names=referenced_names(query),
                variables=variables,
                definitions=definitions,
                date_from=date_from,
                date_to=date_to,
                depth=depth,
            )
        sql = substitute_sql(query or "", variables)
        if sql.unresolved:
            raise ValueError(unresolved_message(sql.unresolved))
        try:
            options = run_metrics_sql_values(team, sql.sql, date_from, date_to, MAX_VARIABLE_OPTIONS, sql.placeholders)
        except ExposedHogQLError as exc:
            raise ValueError(str(exc)) from exc
    return list(dict.fromkeys(str(option) for option in options))[:MAX_VARIABLE_OPTIONS]
