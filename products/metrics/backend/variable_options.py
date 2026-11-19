"""The options of a metrics dashboard variable, from a static list or a PromQL or SQL query."""

from __future__ import annotations

import re
import json
import time
import uuid
import hashlib
import datetime as dt
import dataclasses
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager, nullcontext
from itertools import islice
from typing import Any

from django.core.cache import caches
from django.utils.connection import ConnectionProxy

import re2

from posthog.schema import MetricsDashboardVariable, MetricsDashboardVariableSource

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError

from posthog.clickhouse.client.connection import MAX_QUERY_SIZE_BYTES
from posthog.dataclasses import frozen
from posthog.errors import ExposedCHQueryError
from posthog.models import Team

from products.metrics.backend.metric_query_runner import MAX_QUERY_SPAN
from products.metrics.backend.promql import PromQLQueryError, snuffle_payload
from products.metrics.backend.sql_mode import run_metrics_sql_values
from products.metrics.backend.variables import (
    Variable,
    promql_string_escape,
    sql_referenced_names,
    substitute_promql,
    substitute_sql,
    unresolved_message,
    with_values,
)

MAX_VARIABLE_OPTIONS = 1000
MAX_EXPANDED_VARIABLES = 50
_FUNCTION = re.compile(r"^\s*(?P<name>label_values|label_names|metrics|query_result)\s*\((?P<args>.*)\)\s*$", re.DOTALL)
_LABEL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OPTIONS_CACHE_SECONDS = 60
# Tiles of one dashboard run at the same time. One of them loads the options and holds a lock while it runs.
# The lock outlasts the slowest query, a 60 second Snuffle or ClickHouse query, so a slow query runs only once.
_OPTIONS_LOCK_SECONDS = 90
_OPTIONS_POLL_SECONDS = 0.1
# A failed load is shared with the callers that wait for it, so they do not run the same failing query again.
_OPTIONS_ERROR_SECONDS = 10
cache = ConnectionProxy(caches, "metrics_variable_options")
# The selection API accepts values up to this length, so a longer option could not be selected.
MAX_OPTION_LENGTH = 1024
# A regex can capture a short option from a longer value, so a query with a regex keeps longer values for it.
_MAX_REGEX_SOURCE_LENGTH = 16 * 1024


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
    # A scalar or a string result is one `[timestamp, value]` pair, and Grafana shows only its value.
    if isinstance(data, dict) and data.get("resultType") in ("scalar", "string"):
        return [str(results[1])] if isinstance(results, list) and len(results) == 2 else []
    lines = (_query_result_line(result) for result in results or [])
    return list(islice((line for line in lines if line is not None), MAX_VARIABLE_OPTIONS))


def re2_pattern(regex: str | None) -> str:
    """The RE2 pattern of a variable regex. Grafana writes `/pattern/flags`, and RE2 takes the flags inline."""
    pattern = (regex or "").strip()
    if not (pattern.startswith("/") and pattern.rfind("/") > 0):
        return pattern
    flags = "".join(flag for flag in "ims" if flag in pattern[pattern.rfind("/") + 1 :])
    body = pattern[1 : pattern.rfind("/")]
    return f"(?{flags}){body}" if flags and body else body


def compile_regex(regex: str | None) -> Any:
    """The compiled variable regex, or None without one. Raises `ValueError` for a pattern that RE2 rejects.

    RE2 runs the pattern in linear time, so a user pattern cannot backtrack without end. A dot matches a newline,
    as in the ClickHouse functions that SQL queries use.
    """
    pattern = re2_pattern(regex)
    if not pattern:
        return None
    try:
        return re2.compile(f"(?s){pattern}")
    except re2.error as exc:
        raise ValueError(f"The variable regex cannot be used: {exc}") from exc


def apply_regex(options: list[str], regex: str | None) -> list[str]:
    """Keep the options that match the variable's regex. With a capture group, the option is the first group."""
    compiled = compile_regex(regex) if options else None
    if compiled is None:
        return options
    matched: list[str] = []
    for option in options:
        match = compiled.search(option)
        if match is None:
            continue
        # An option whose group does not take part in the match has no value, as in the dashboard selects.
        value = (match.group(1) or "") if compiled.groups else option
        if value or not compiled.groups:
            matched.append(value)
    return list(dict.fromkeys(matched))


def check_options_window(date_from: dt.datetime, date_to: dt.datetime) -> None:
    if date_from >= date_to:
        raise ValueError("The start of the window must be before its end.")
    # Tiles have the same cap, so an options query cannot scan more history than a tile.
    if date_to - date_from > MAX_QUERY_SPAN:
        raise ValueError(f"The window of the variable options can be at most {MAX_QUERY_SPAN.days} days.")


@dataclasses.dataclass(frozen=False)
class _Expansion:
    # Nested SQL variable queries share one expansion, so each variable set to All loads once per query.
    filled: dict[str, Variable]
    resolved: set[str] = dataclasses.field(default_factory=set)
    started: int = 0
    characters: int = 0


def fill_all_values(
    *,
    team: Team,
    names: Iterable[str],
    variables: Mapping[str, Variable],
    definitions: Mapping[str, MetricsDashboardVariable],
    date_from: dt.datetime,
    date_to: dt.datetime,
    slot: Callable[[], AbstractContextManager[None]] = nullcontext,
) -> dict[str, Variable]:
    """SQL cannot match everything, so each variable set to All gets the values of all its options."""
    check_options_window(date_from, date_to)
    expansion = _Expansion(filled=dict(variables))
    _expand(
        team=team,
        names=names,
        expansion=expansion,
        definitions=definitions,
        date_from=date_from,
        date_to=date_to,
        path=frozenset(),
        slot=slot,
    )
    return expansion.filled


def _expand(
    *,
    team: Team,
    names: Iterable[str],
    expansion: _Expansion,
    definitions: Mapping[str, MetricsDashboardVariable],
    date_from: dt.datetime,
    date_to: dt.datetime,
    path: frozenset[str],
    slot: Callable[[], AbstractContextManager[None]],
) -> None:
    for name in names:
        variable = expansion.filled.get(name)
        definition = definitions.get(name)
        if name in expansion.resolved or variable is None or not variable.is_all or variable.values:
            continue
        if definition is None:
            continue
        if name in path:
            raise ValueError(f"The variable queries refer to each other in a loop through ${name}.")
        if expansion.started >= MAX_EXPANDED_VARIABLES:
            raise ValueError(f"A query can use at most {MAX_EXPANDED_VARIABLES} variables that are set to All.")
        expansion.started += 1
        options = list_variable_options(
            team=team,
            source=definition.source,
            query=definition.query,
            custom_values=definition.customValues,
            regex=definition.regex,
            variables=expansion.filled,
            definitions=definitions,
            date_from=date_from,
            date_to=date_to,
            path=path | {name},
            slot=slot,
            expansion=expansion,
        )
        # The values go into the query text, which ClickHouse caps at MAX_QUERY_SIZE_BYTES. Half of it is left for the query.
        expansion.characters += sum(len(option) + 4 for option in options)
        if expansion.characters > MAX_QUERY_SIZE_BYTES // 2:
            raise ValueError("The variables set to All have too many values for one query. Select fewer values.")
        expansion.filled[name] = with_values(variable, options)
        expansion.resolved.add(name)


def _cache_key(team: Team, parts: list[Any]) -> str:
    payload = json.dumps(parts, sort_keys=True, default=str)
    return f"metrics:variable_options:{team.pk}:{hashlib.sha256(payload.encode()).hexdigest()}"


def _query_cache_key(
    team: Team,
    source: MetricsDashboardVariableSource,
    text: str,
    placeholders: Mapping[str, ast.Expr],
    date_from: dt.datetime,
    date_to: dt.datetime,
    regex: str | None,
) -> str:
    """The key of the query that runs, with the variable values in it, so a dashboard select and a tile share it."""
    values = {
        key: [item.value for item in expr.exprs if isinstance(item, ast.Constant)]
        if isinstance(expr, ast.Tuple)
        else expr.value
        if isinstance(expr, ast.Constant)
        else repr(expr)
        for key, expr in placeholders.items()
    }
    # UTC minutes, so that the browser and the tiles, which compute "now" a few seconds apart, share the key.
    window = [moment.astimezone(dt.UTC).isoformat(timespec="minutes") for moment in (date_from, date_to)]
    return _cache_key(team, [source.value, text, values, window, re2_pattern(regex)])


def _shared_options(
    key: str, load: Callable[[], list[str]], slot: Callable[[], AbstractContextManager[None]] = nullcontext
) -> list[str]:
    """The options from the shared cache. When several callers miss at once, one runs `load` and the others wait.

    Only the caller that holds the lock runs `load`, inside `slot`. A cache hit or a waiter takes no
    slot. A load that fails with an error the user can see gives the waiters the same error. Any other
    failure releases the lock, and the next waiter loads.
    """
    lock_key = f"{key}:lock"
    error_key = f"{key}:error"
    token = uuid.uuid4().hex
    deadline = time.monotonic() + _OPTIONS_LOCK_SECONDS
    while True:
        options = _published_options(key, error_key)
        if options is not None:
            return options
        if cache.add(lock_key, token, _OPTIONS_LOCK_SECONDS):
            break
        if time.monotonic() >= deadline:
            raise ValueError("The variable values are still loading. Try again in a moment.")
        time.sleep(_OPTIONS_POLL_SECONDS)
    try:
        # Another loader can publish between the read above and taking the lock.
        options = _published_options(key, error_key)
        if options is not None:
            return options
        try:
            with slot():
                options = [option for option in load() if len(str(option)) <= MAX_OPTION_LENGTH]
        except (ValueError, ExposedHogQLError, ExposedCHQueryError) as exc:
            cache.set(error_key, str(exc), _OPTIONS_ERROR_SECONDS)
            raise
        cache.set(key, options, _OPTIONS_CACHE_SECONDS)
        return options
    finally:
        # A load that outlived the lock must not release the lock of the loader that took it over.
        if cache.get(lock_key) == token:
            cache.delete(lock_key)


def _published_options(key: str, error_key: str) -> list[str] | None:
    if (error := cache.get(error_key)) is not None:
        raise ValueError(error)
    return cache.get(key)


def list_variable_options(
    *,
    team: Team,
    source: MetricsDashboardVariableSource,
    query: str | None,
    custom_values: list[str] | None,
    variables: Mapping[str, Variable],
    date_from: dt.datetime,
    date_to: dt.datetime,
    regex: str | None = None,
    definitions: Mapping[str, MetricsDashboardVariable] | None = None,
    path: frozenset[str] = frozenset(),
    slot: Callable[[], AbstractContextManager[None]] = nullcontext,
    expansion: _Expansion | None = None,
) -> list[str]:
    """The options of one variable, in the order the source gives them. Raises `ValueError` for a bad query.

    `definitions` lets a SQL query use another variable that is set to All, by loading its options.
    `slot` holds a concurrency slot while the query runs. `regex` filters the options of a query, and a list
    ignores it, because its select shows every value.
    """
    # The cache key holds whole minutes, so the query runs on the same whole minutes.
    date_from = date_from.replace(second=0, microsecond=0)
    if date_to.second or date_to.microsecond:
        date_to = date_to.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
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
        key = _query_cache_key(team, source, substitution.text, {}, date_from, date_to, regex)
        options = _shared_options(
            key, lambda: apply_regex(_promql_options(team, substitution.text, date_from, date_to), regex), slot
        )
    else:
        if definitions:
            expansion = expansion or _Expansion(filled=dict(variables))
            _expand(
                team=team,
                names=sql_referenced_names(query),
                expansion=expansion,
                definitions=definitions,
                date_from=date_from,
                date_to=date_to,
                path=path,
                slot=slot,
            )
            variables = expansion.filled
        sql = substitute_sql(query or "", variables)
        if sql.unresolved:
            raise ValueError(unresolved_message(sql.unresolved))
        key = _query_cache_key(team, source, sql.sql, sql.placeholders, date_from, date_to, regex)
        try:
            options = _shared_options(
                key,
                lambda: apply_regex(
                    run_metrics_sql_values(
                        team,
                        sql.sql,
                        date_from,
                        date_to,
                        MAX_VARIABLE_OPTIONS,
                        sql.placeholders,
                        max_length=_MAX_REGEX_SOURCE_LENGTH if regex else MAX_OPTION_LENGTH,
                    ),
                    regex,
                ),
                slot,
            )
        except (ExposedHogQLError, ExposedCHQueryError) as exc:
            raise ValueError(str(exc)) from exc
    return list(dict.fromkeys(str(option) for option in options))[:MAX_VARIABLE_OPTIONS]
