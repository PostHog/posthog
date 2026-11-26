"""Run a PromQL metrics insight as a Snuffle range query, or an instant query for one value per series.

The range and step come from the same interval ladder as the builder engine, so a PromQL insight
and a builder insight over the same window chart the same buckets.
"""

import re
import json
import math
import datetime as dt
from typing import Any

import requests

from posthog.api.snuffle_proxy import SnuffleNotConfiguredError, snuffle_request
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.workload import Workload
from posthog.models import Team

from products.metrics.backend.facade.contracts import MetricPoint, MetricSeries, PromQLQueryError
from products.metrics.backend.metric_query_runner import _align_to_interval, _interval_step, _resolve_interval
from products.metrics.backend.query_counts import record_promql_query
from products.metrics.backend.series import rank_and_fill_series

# The label that builderToPromql adds to keep the series of a multi-series query apart.
CLAUSE_LABEL = "clause"
_QUERY_PATHS = frozenset({"/api/v1/query", "/api/v1/query_range"})
# builderToPromql sets the label with `label_replace(<series>, "clause", "<alias>", "", "")`. Without
# that call, a `clause` label belongs to the user's data.
_SETS_CLAUSE_LABEL = re.compile(r'label_replace\s*\(.*,\s*"clause"\s*,\s*"', re.DOTALL)
# builderToPromql writes quantiles of the same buckets as `histogram_quantiles("clause", 0.5, 0.9, <buckets>)`,
# so Snuffle reads the buckets one time. The label holds the quantile. The quantiles belong to the
# clauses a, b, c, ... in order.
_SHARED_HISTOGRAM_QUANTILES = re.compile(
    r'^\s*histogram_quantiles\s*\(\s*"clause"\s*((?:,\s*[0-9.eE+-]+\s*)+),', re.DOTALL
)
# Grafana's dashboard range, as `$__range` (a duration), `$__range_s` or `$__range_ms` (a number). Snuffle
# does not know them, so they become the chart's date range before the query goes out. A `\$__range` in a
# regex matcher is an escaped literal dollar, so it stays.
_RANGE_VARIABLE = re.compile(r"(?<!\\)\$\{__range(?P<braced>_s|_ms)?\}|(?<!\\)\$__range(?P<plain>_s|_ms)?\b")


def _sample_value(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _error_message(response: requests.Response, body: bytes | None) -> str:
    fallback = f"The PromQL query failed with status {response.status_code}."
    try:
        payload = _decoded(response, body)
    except ValueError:
        return fallback
    return str(payload.get("error") or fallback) if isinstance(payload, dict) else fallback


def _decoded(response: requests.Response, body: bytes | None) -> Any:
    return response.json() if body is None else json.loads(body)


class PromQLResponseTooLargeError(PromQLQueryError):
    """The response passed the caller's `max_bytes`."""


def _read_body(response: requests.Response, max_bytes: int | None) -> bytes | None:
    """The body read no further than `max_bytes`, so an oversized result is never held whole. None when
    unbounded, so the response decodes itself."""
    if max_bytes is None:
        return None
    try:
        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            body.extend(chunk)
            if len(body) > max_bytes:
                raise PromQLResponseTooLargeError(
                    f"The PromQL query returned more than {max_bytes // 1_000_000} MB. Aggregate it, for example "
                    "with sum by (...), or look back over a shorter window."
                )
        return bytes(body)
    finally:
        response.close()


def _quantile_clauses(expr: str) -> dict[float, str]:
    """The clause alias of each quantile in a `histogram_quantiles("clause", ...)` query."""
    match = _SHARED_HISTOGRAM_QUANTILES.match(expr)
    if not match:
        return {}
    try:
        quantiles = [float(value) for value in match.group(1).split(",")[1:]]
    except ValueError:
        return {}
    return {quantile: chr(ord("a") + index) for index, quantile in enumerate(quantiles)}


def _clause_alias(value: str | None, quantile_clauses: dict[float, str]) -> str | None:
    if value is None or not quantile_clauses:
        return value
    try:
        return quantile_clauses.get(float(value), value)
    except ValueError:
        return value


def fill_range_variables(expr: str, date_from: dt.datetime, date_to: dt.datetime) -> str:
    # Timestamps, not datetime subtraction, which counts wall-clock time across a DST change.
    milliseconds = max(round((date_to.timestamp() - date_from.timestamp()) * 1000), 1000)
    seconds = round(milliseconds / 1000)
    values = {None: f"{seconds}s", "_s": str(seconds), "_ms": str(milliseconds)}
    return _RANGE_VARIABLE.sub(lambda match: values[match.group("braced") or match.group("plain")], expr)


def snuffle_payload(
    team: Team,
    method: str,
    path: str,
    *,
    data: dict[str, str] | None = None,
    params: dict[str, list[str]] | None = None,
    timeout: float | None = None,
    ch_user: ClickHouseUser | None = None,
    max_bytes: int | None = None,
    record_query: bool = True,
) -> dict[str, Any]:
    """Send one Prometheus API request to Snuffle and return its JSON body. Errors are safe to show.

    With `max_bytes`, a larger body fails the query before it is decoded. `record_query=False` keeps a query that
    no user wrote, such as a precompute fill, out of the team's query counts."""
    if record_query and path in _QUERY_PATHS and data and data.get("query"):
        record_promql_query(team, data["query"])
    try:
        response = snuffle_request(
            team.pk,
            method,
            path,
            data=data,
            params=params,
            timeout=timeout,
            ch_user=ch_user,
            workload=Workload.METRICS,
            stream=max_bytes is not None,
        )
        body = _read_body(response, max_bytes)
    except SnuffleNotConfiguredError as exc:
        # Deployment config, not the query, so an alert waiting on it is not counted as broken.
        raise PromQLQueryError("PromQL queries are not available on this PostHog instance.", transient=True) from exc
    except requests.Timeout as exc:
        raise PromQLQueryError("The PromQL query timed out. Try a shorter date range.", transient=True) from exc
    except requests.RequestException as exc:
        raise PromQLQueryError("The PromQL query backend cannot be reached. Try again later.", transient=True) from exc

    if response.status_code in (401, 403) or response.status_code >= 500:
        raise PromQLQueryError("The PromQL query backend failed. Try again later.", transient=True)
    # Snuffle's rate limit, which passes once the budget refills.
    if response.status_code == 429:
        raise PromQLQueryError(_error_message(response, body), transient=True)
    if response.status_code >= 400:
        raise PromQLQueryError(_error_message(response, body))
    try:
        payload = _decoded(response, body)
    except ValueError as exc:
        raise PromQLQueryError("The PromQL query backend sent a response that cannot be read.", transient=True) from exc
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise PromQLQueryError(_error_message(response, body))
    return payload


def run_promql_range(
    team: Team,
    expr: str,
    date_from: dt.datetime,
    date_to: dt.datetime,
    interval: str | None,
    *,
    record_query: bool = True,
) -> list[MetricSeries]:
    resolved = _resolve_interval(date_from, date_to, interval)
    step = _interval_step(resolved)
    start = _align_to_interval(date_from, resolved, tzinfo=team.timezone_info)
    results = promql_range_results(
        team, fill_range_variables(expr, date_from, date_to), start, date_to, step, record_query=record_query
    )
    # PromQL has no sample for a time that a series does not report, so the chart shows a gap.
    return series_from_results(team, expr, results)


def promql_range_results(
    team: Team,
    expr: str,
    start: dt.datetime,
    end: dt.datetime,
    step: dt.timedelta,
    *,
    record_query: bool = True,
    max_bytes: int | None = None,
) -> list[dict[str, Any]]:
    """The raw `matrix` results of a Snuffle range query: one `{metric, values}` per series."""
    payload = snuffle_payload(
        team,
        "POST",
        "/api/v1/query_range",
        data={
            "query": expr,
            "start": str(start.timestamp()),
            "end": str(end.timestamp()),
            "step": str(int(step.total_seconds())),
        },
        record_query=record_query,
        max_bytes=max_bytes,
    )

    data = payload.get("data") or {}
    result_type = data.get("resultType")
    results = data.get("result") or []
    if result_type == "scalar":
        # A constant expression: one value for the whole range.
        results = [{"metric": {}, "values": [results]}] if results else []
    elif result_type != "matrix":
        raise PromQLQueryError(f"A PromQL range query cannot return a {result_type} result.")
    return results


def run_promql_instant(team: Team, expr: str, time: dt.datetime) -> list[MetricSeries]:
    """Run a PromQL instant query on Snuffle: one value per series at `time`."""
    payload = snuffle_payload(team, "POST", "/api/v1/query", data={"query": expr, "time": str(time.timestamp())})

    data = payload.get("data") or {}
    result_type = data.get("resultType")
    results = data.get("result") or []
    if result_type == "scalar":
        results = [{"metric": {}, "values": [results]}] if results else []
    elif result_type == "vector":
        results = [{**result, "values": [result["value"]] if result.get("value") else []} for result in results]
    elif result_type == "matrix":
        raise PromQLQueryError(
            "The expression returns a range vector, which an instant query cannot show. "
            "Wrap the range selector in a function such as rate(...[5m]) or max_over_time(...[5m])."
        )
    else:
        raise PromQLQueryError(f"A PromQL instant query cannot return a {result_type} result.")
    return series_from_results(team, expr, results)


def series_from_results(team: Team, expr: str, results: list[dict[str, Any]]) -> list[MetricSeries]:
    tzinfo = team.timezone_info
    quantile_clauses = _quantile_clauses(expr)
    marks_clauses = bool(quantile_clauses) or bool(_SETS_CLAUSE_LABEL.search(expr))
    rows: list[tuple[dict[str, str], str | None, str | None, list[MetricPoint]]] = []
    for result in results:
        labels = {str(key): str(value) for key, value in (result.get("metric") or {}).items()}
        metric_name = labels.pop("__name__", None)
        clause = _clause_alias(labels.pop(CLAUSE_LABEL, None), quantile_clauses) if marks_clauses else None
        points = [
            MetricPoint(
                time=dt.datetime.fromtimestamp(float(timestamp), tz=tzinfo).isoformat(),
                value=_sample_value(value),
            )
            for timestamp, value in result.get("values") or []
        ]
        rows.append((labels, metric_name, clause, points))
    return rank_and_fill_series(rows, fill=None)
