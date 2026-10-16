"""The options of a metrics dashboard variable, from a static list or a PromQL or SQL query.

The query can refer to other variables, so a variable can depend on the selection of another one.
The frontend applies the variable's regex, because a user pattern must not run on the server.
"""

from __future__ import annotations

import re
import datetime as dt
from collections.abc import Mapping

import requests

from posthog.schema import MetricsDashboardVariableSource

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.snuffle_proxy import SnuffleNotConfiguredError, snuffle_request
from posthog.models import Team

from products.metrics.backend.promql import PromQLQueryError, _error_message
from products.metrics.backend.sql_mode import run_metrics_sql_values
from products.metrics.backend.variables import Variable, substitute_promql, substitute_sql, unresolved_message

MAX_VARIABLE_OPTIONS = 1000
_FUNCTION = re.compile(r"^\s*(?P<name>label_values|label_names|metrics|query_result)\s*\((?P<args>.*)\)\s*$", re.DOTALL)
_LABEL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _split_last_argument(args: str) -> tuple[str, str]:
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
        return "", args.strip()
    return args[:split_at].strip(), args[split_at + 1 :].strip()


def _snuffle_data(team: Team, method: str, path: str, params: dict[str, list[str]] | dict[str, str]) -> object:
    try:
        response = snuffle_request(team.pk, method, path, params=params)
    except SnuffleNotConfiguredError as exc:
        raise PromQLQueryError("PromQL queries are not available on this PostHog instance.") from exc
    except requests.Timeout as exc:
        raise PromQLQueryError("The variable query timed out. Try a shorter date range.") from exc
    except requests.RequestException as exc:
        raise PromQLQueryError("The PromQL query backend cannot be reached. Try again later.") from exc
    if response.status_code in (401, 403) or response.status_code >= 500:
        raise PromQLQueryError("The PromQL query backend failed. Try again later.")
    if response.status_code >= 400:
        raise PromQLQueryError(_error_message(response))
    try:
        payload = response.json()
    except ValueError as exc:
        raise PromQLQueryError("The PromQL query backend sent a response that cannot be read.") from exc
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise PromQLQueryError(_error_message(response))
    return payload.get("data")


def _strings(data: object) -> list[str]:
    return [str(item) for item in data] if isinstance(data, list) else []


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
    window = {"start": str(date_from.timestamp()), "end": str(date_to.timestamp())}
    if name == "label_values":
        selector, label = _split_last_argument(args)
        if not _LABEL_NAME.match(label):
            raise PromQLQueryError(f'"{label}" is not a label name.')
        params: dict[str, list[str]] = {key: [value] for key, value in window.items()}
        if selector:
            params["match[]"] = [selector]
        return _strings(_snuffle_data(team, "GET", f"/api/v1/label/{label}/values", params))
    if name == "label_names":
        params = {key: [value] for key, value in window.items()}
        if args:
            params["match[]"] = [args]
        return _strings(_snuffle_data(team, "GET", "/api/v1/labels", params))
    if name == "metrics":
        names = _strings(_snuffle_data(team, "GET", "/api/v1/label/__name__/values", window))
        if not args:
            return names
        # Grafana treats the argument as a regex. The frontend applies user patterns, so this keeps a substring match.
        return [metric for metric in names if args.strip("\"'") in metric]
    if not args:
        raise PromQLQueryError("query_result needs a PromQL expression.")
    data = _snuffle_data(team, "POST", "/api/v1/query", {"query": args, "time": window["end"]})
    results = data.get("result") if isinstance(data, dict) else None
    lines = (_query_result_line(result) for result in results or [])
    return [line for line in lines if line is not None]


def list_variable_options(
    *,
    team: Team,
    source: MetricsDashboardVariableSource,
    query: str | None,
    custom_values: list[str] | None,
    variables: Mapping[str, Variable],
    date_from: dt.datetime,
    date_to: dt.datetime,
) -> list[str]:
    """The options of one variable, in the order the source gives them. Raises `ValueError` for a bad query."""
    if source == MetricsDashboardVariableSource.CUSTOM:
        options = [value for value in custom_values or [] if value]
    elif source == MetricsDashboardVariableSource.TEXTBOX:
        options = []
    elif not (query or "").strip():
        raise ValueError("Write a query for the variable first.")
    elif source == MetricsDashboardVariableSource.PROMQL:
        text, unresolved = substitute_promql(query or "", variables)
        if unresolved:
            raise ValueError(unresolved_message(unresolved))
        options = _promql_options(team, text, date_from, date_to)
    else:
        text = substitute_sql(query or "", variables)
        try:
            options = run_metrics_sql_values(team, text, date_from, date_to, MAX_VARIABLE_OPTIONS)
        except ExposedHogQLError as exc:
            raise ValueError(str(exc)) from exc
    return list(dict.fromkeys(options))[:MAX_VARIABLE_OPTIONS]
