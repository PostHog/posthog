"""Run a PromQL metrics insight as a Snuffle range query.

The range and step come from the same interval ladder as the builder engine, so a PromQL insight
and a builder insight over the same window chart the same buckets.
"""

import re
import math
import datetime as dt
from typing import Any

import requests

from posthog.api.snuffle_proxy import SnuffleNotConfiguredError, snuffle_request
from posthog.models import Team

from products.metrics.backend.facade.contracts import MetricPoint, MetricSeries
from products.metrics.backend.metric_query_runner import _align_to_interval, _interval_step, _resolve_interval
from products.metrics.backend.series import rank_and_fill_series

# The label that builderToPromql adds to keep the series of a multi-series query apart.
CLAUSE_LABEL = "clause"
# builderToPromql sets the label with `label_replace(<series>, "clause", "<alias>", "", "")`. Without
# that call, a `clause` label belongs to the user's data.
_SETS_CLAUSE_LABEL = re.compile(r'label_replace\s*\(.*,\s*"clause"\s*,\s*"', re.DOTALL)
# builderToPromql writes quantiles of the same buckets as `histogram_quantiles("clause", 0.5, 0.9, <buckets>)`,
# so Snuffle reads the buckets one time. The label holds the quantile. The quantiles belong to the
# clauses a, b, c, ... in order.
_SHARED_HISTOGRAM_QUANTILES = re.compile(
    r'^\s*histogram_quantiles\s*\(\s*"clause"\s*((?:,\s*[0-9.eE+-]+\s*)+),', re.DOTALL
)


class PromQLQueryError(ValueError):
    """A PromQL query that Snuffle rejected or could not run. The message is safe to show."""


def _sample_value(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"The PromQL query failed with status {response.status_code}."
    return str(payload.get("error") or f"The PromQL query failed with status {response.status_code}.")


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


def snuffle_payload(
    team: Team,
    method: str,
    path: str,
    *,
    data: dict[str, str] | None = None,
    params: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Send one Prometheus API request to Snuffle and return its JSON body. Errors are safe to show."""
    try:
        response = snuffle_request(team.pk, method, path, data=data, params=params)
    except SnuffleNotConfiguredError as exc:
        raise PromQLQueryError("PromQL queries are not available on this PostHog instance.") from exc
    except requests.Timeout as exc:
        raise PromQLQueryError("The PromQL query timed out. Try a shorter date range.") from exc
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
    return payload


def run_promql_range(
    team: Team, expr: str, date_from: dt.datetime, date_to: dt.datetime, interval: str | None
) -> list[MetricSeries]:
    resolved = _resolve_interval(date_from, date_to, interval)
    step = _interval_step(resolved)
    start = _align_to_interval(date_from, resolved, tzinfo=team.timezone_info)
    payload = snuffle_payload(
        team,
        "POST",
        "/api/v1/query_range",
        data={
            "query": expr,
            "start": str(start.timestamp()),
            "end": str(date_to.timestamp()),
            "step": str(int(step.total_seconds())),
        },
    )

    data = payload.get("data") or {}
    result_type = data.get("resultType")
    results = data.get("result") or []
    if result_type == "scalar":
        # A constant expression: one value for the whole range.
        results = [{"metric": {}, "values": [results]}] if results else []
    elif result_type != "matrix":
        raise PromQLQueryError(f"A PromQL range query cannot return a {result_type} result.")

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
    # PromQL has no sample for a time that a series does not report, so the chart shows a gap.
    return rank_and_fill_series(rows, fill=None)
