"""Run a PromQL metrics insight as a Snuffle range query.

The range and step come from the same interval ladder as the builder engine, so a PromQL insight
and a builder insight over the same window chart the same buckets.
"""

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


def run_promql_range(
    team: Team, expr: str, date_from: dt.datetime, date_to: dt.datetime, interval: str | None
) -> list[MetricSeries]:
    resolved = _resolve_interval(date_from, date_to, interval)
    step = _interval_step(resolved)
    start = _align_to_interval(date_from, resolved, tzinfo=team.timezone_info)
    try:
        response = snuffle_request(
            team.pk,
            "POST",
            "/api/v1/query_range",
            data={
                "query": expr,
                "start": str(start.timestamp()),
                "end": str(date_to.timestamp()),
                "step": str(int(step.total_seconds())),
            },
        )
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
    if payload.get("status") != "success":
        raise PromQLQueryError(_error_message(response))

    data = payload.get("data") or {}
    result_type = data.get("resultType")
    results = data.get("result") or []
    if result_type == "scalar":
        # A constant expression: one value for the whole range.
        results = [{"metric": {}, "values": [results]}]
    elif result_type != "matrix":
        raise PromQLQueryError(f"A PromQL range query cannot return a {result_type} result.")

    tzinfo = team.timezone_info
    rows: list[tuple[dict[str, str], str | None, str | None, list[MetricPoint]]] = []
    for result in results:
        labels = {str(key): str(value) for key, value in (result.get("metric") or {}).items()}
        metric_name = labels.pop("__name__", None)
        clause = labels.pop(CLAUSE_LABEL, None)
        points = [
            MetricPoint(
                time=dt.datetime.fromtimestamp(float(timestamp), tz=tzinfo).isoformat(),
                value=_sample_value(value),
            )
            for timestamp, value in result.get("values") or []
        ]
        rows.append((labels, metric_name, clause, points))
    return rank_and_fill_series(rows)
