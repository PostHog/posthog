"""Checks of a generated dashboard against the data of its source project.

The attribute profile finds the attributes that suit a dashboard variable, and the attributes with one value,
which make a useless variable. A pair check finds two variables that select the same thing. A panel run finds
the panels whose query fails as a dashboard tile runs it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any

from django.db import connections

import structlog

from posthog.schema import DashboardFilter, DateRange, MetricsDashboardVariable, MetricsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.database.schema.metrics import HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.dataclasses import frozen
from posthog.models import Team

from products.metrics.backend.hogql_queries.metrics_query_runner import MetricsQueryRunner

logger = structlog.get_logger(__name__)

PROFILE_LOOKBACK = dt.timedelta(hours=24)
RUN_DATE_FROM = "-1h"
RUN_WORKERS = 4
MIN_VARIABLE_VALUES = 2
MAX_CANDIDATE_VALUES = 20
MAX_CANDIDATES = 8
# Two attributes are one to one when they form at most this many pairs per value of the attribute with fewer values.
ONE_TO_ONE_SLACK = 1.1
SERVICE_ATTRIBUTE = "service_name"
_SERVICE_ATTRIBUTES = frozenset({"service_name", "service.name"})
_QUERY_SETTINGS = HogQLGlobalSettings(max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES)


@frozen
class AttributeStats:
    value_count: int
    metric_count: int


def _attribute(name: str) -> str:
    return SERVICE_ATTRIBUTE if name in _SERVICE_ATTRIBUTES else name


def _names(metric_names: Sequence[str]) -> ast.Tuple:
    return ast.Tuple(exprs=[ast.Constant(value=name) for name in sorted(set(metric_names))])


def _value(attribute: str) -> ast.Expr:
    if _attribute(attribute) == SERVICE_ATTRIBUTE:
        return ast.Field(chain=["service_name"])
    return parse_expr(
        "if(arrayElement(resource_attributes, {key}) != '', arrayElement(resource_attributes, {key}), "
        "arrayElement(attributes, {key}))",
        placeholders={"key": ast.Constant(value=attribute)},
    )


def _since() -> dt.datetime:
    return dt.datetime.now(dt.UTC) - PROFILE_LOOKBACK


def attribute_profile(team: Team, metric_names: Sequence[str]) -> dict[str, AttributeStats]:
    """The number of values of each attribute of the metrics, and the number of the metrics that have it."""
    query = parse_select(
        """
            SELECT attribute_key, uniqCombined64(attribute_value), uniqCombined64(metric_name)
            FROM (
                SELECT
                    metric_name,
                    arrayJoin(arrayConcat(
                        mapKeys(attributes),
                        arrayFilter(name -> name != 'service.name', mapKeys(resource_attributes)),
                        ['service_name']
                    )) AS attribute_key,
                    if(attribute_key = 'service_name', service_name,
                        if(arrayElement(resource_attributes, attribute_key) != '',
                            arrayElement(resource_attributes, attribute_key),
                            arrayElement(attributes, attribute_key))) AS attribute_value
                FROM posthog.metric_series
                WHERE last_seen >= {since} AND metric_name IN {names}
            )
            WHERE attribute_value != ''
            GROUP BY attribute_key
        """,
        placeholders={"since": ast.Constant(value=_since()), "names": _names(metric_names)},
    )
    response = execute_hogql_query(
        query_type="MetricsDashboardAttributeProfile",
        query=query,
        team=team,
        workload=Workload.LOGS,
        settings=_QUERY_SETTINGS,
    )
    return {
        str(key): AttributeStats(value_count=int(values), metric_count=int(metrics))
        for key, values, metrics in response.results
    }


def variable_candidates(profile: Mapping[str, AttributeStats], metric_count: int) -> list[str]:
    """The attributes that most of the metrics have, with a few values each: the ones a person would pick from."""
    candidates = [
        (key, stats)
        for key, stats in profile.items()
        if MIN_VARIABLE_VALUES <= stats.value_count <= MAX_CANDIDATE_VALUES and stats.metric_count * 2 > metric_count
    ]
    candidates.sort(key=lambda item: (-item[1].metric_count, item[1].value_count, item[0]))
    return [key for key, _ in candidates[:MAX_CANDIDATES]]


def one_to_one(team: Team, metric_names: Sequence[str], first: str, second: str) -> bool:
    """Whether each value of one attribute goes with one value of the other, in nearly every series."""
    query = parse_select(
        """
            SELECT uniqCombined64(a), uniqCombined64(b), uniqCombined64(a, b)
            FROM (
                SELECT {first} AS a, {second} AS b
                FROM posthog.metric_series
                WHERE last_seen >= {since} AND metric_name IN {names}
            )
            WHERE a != '' AND b != ''
        """,
        placeholders={
            "first": _value(first),
            "second": _value(second),
            "since": ast.Constant(value=_since()),
            "names": _names(metric_names),
        },
    )
    response = execute_hogql_query(
        query_type="MetricsDashboardVariablePair",
        query=query,
        team=team,
        workload=Workload.LOGS,
        settings=_QUERY_SETTINGS,
    )
    first_count, second_count, pairs = (int(value) for value in response.results[0])
    fewer = min(first_count, second_count)
    return fewer > 0 and pairs <= fewer * ONE_TO_ONE_SLACK


def _run(team: Team, query: dict[str, Any], variables: Sequence[MetricsDashboardVariable]) -> str | None:
    try:
        runner = MetricsQueryRunner(
            query=MetricsQuery.model_validate({**query, "dateRange": DateRange(date_from=RUN_DATE_FROM)}),
            team=team,
        )
        if variables:
            runner.apply_dashboard_filters(DashboardFilter(metricVariables=list(variables)))
        runner.calculate()
    except ExposedHogQLError as error:
        return str(error)
    except Exception:
        logger.exception("metrics_suggested_dashboards_panel_run_failed", team_id=team.id)
        return "The query could not run."
    finally:
        connections.close_all()
    return None


class ProjectChecks:
    """The checks for one generation. The profile comes from `attribute_profile`, or is None when it failed."""

    def __init__(
        self, team: Team, metric_names: Sequence[str], value_counts: Mapping[str, int] | None, *, deadline: float
    ) -> None:
        self._team = team
        self._metric_names = tuple(metric_names)
        self._value_counts = value_counts
        self._deadline = deadline

    def knows(self, attribute: str) -> bool:
        return self._value_counts is not None and _attribute(attribute) in self._value_counts

    def has_several_values(self, attribute: str) -> bool:
        if self._value_counts is None:
            return True
        return self._value_counts.get(_attribute(attribute), 0) >= MIN_VARIABLE_VALUES

    def one_to_one(self, first: str, second: str) -> bool:
        if _attribute(first) == _attribute(second):
            return True
        try:
            return one_to_one(self._team, self._metric_names, first, second)
        except Exception:
            logger.warning("metrics_suggested_dashboards_variable_pair_failed", team_id=self._team.id)
            return False

    def run_errors(self, queries: Mapping[str, dict[str, Any]], variables: Sequence[dict[str, Any]]) -> dict[str, str]:
        """The error of each query that fails, with every variable set to All."""
        definitions = [MetricsDashboardVariable.model_validate(variable) for variable in variables]
        executor = ThreadPoolExecutor(max_workers=RUN_WORKERS, thread_name_prefix="metrics-suggested-check")
        errors: dict[str, str] = {}
        try:
            futures = {key: executor.submit(_run, self._team, query, definitions) for key, query in queries.items()}
            wait(futures.values(), timeout=self._deadline)
            for key, future in futures.items():
                if not future.done():
                    future.cancel()
                    errors[key] = "The query took too long to run."
                elif (error := future.result()) is not None:
                    errors[key] = error
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return errors
