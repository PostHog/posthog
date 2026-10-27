"""Checks of a generated dashboard against the data of its source project.

The attribute profile finds the attributes that suit a dashboard variable, and the attributes with one value,
which make a useless variable. A pair check finds two variables that select the same thing. A panel run finds
the panels whose query fails as a dashboard tile runs it.
"""

from __future__ import annotations

import time
import datetime as dt
import contextvars
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
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.dataclasses import frozen
from posthog.errors import CH_TRANSIENT_ERRORS
from posthog.models import Team

from products.metrics.backend.hogql_queries.metrics_query_runner import MetricsQueryRunner
from products.metrics.backend.query_concurrency import query_concurrency_slots

logger = structlog.get_logger(__name__)

PROFILE_LOOKBACK = dt.timedelta(hours=24)
RUN_DATE_FROM = "-1h"
RUN_WORKERS = 4
# A panel run that has not started by then is left unchecked, so that the checks end in a bounded time.
RUN_BUDGET_SECONDS = 180.0
MIN_VARIABLE_VALUES = 2
MAX_CANDIDATE_VALUES = 20
MAX_CANDIDATES = 8
# Without a LIMIT, HogQL returns 100 rows. A key past this many is unknown, not a key with no values.
MAX_PROFILE_KEYS = 10_000
# Two attributes are one to one when they form at most 10% more pairs than the attribute with fewer values has
# values, and at most 10% of the series carry only one of them.
ONE_TO_ONE_TOLERANCE = 0.1
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
            LIMIT {limit}
        """,
        placeholders={
            "since": ast.Constant(value=_since()),
            "names": _names(metric_names),
            "limit": ast.Constant(value=MAX_PROFILE_KEYS),
        },
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
    """Whether each value of one attribute goes with one value of the other, in nearly every series.

    A series with only one of the two attributes is one that only that attribute selects.
    """
    query = parse_select(
        """
            SELECT
                uniqIf(a, paired), uniqIf(b, paired), uniqIf(a, b, paired),
                countIf(paired), countIf(not paired)
            FROM (
                SELECT {first} AS a, {second} AS b, a != '' AND b != '' AS paired
                FROM posthog.metric_series
                WHERE last_seen >= {since} AND metric_name IN {names}
            )
            WHERE a != '' OR b != ''
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
    first_count, second_count, pairs, together, apart = (int(value) for value in response.results[0])
    fewer = min(first_count, second_count)
    return (
        fewer > 0 and pairs <= fewer * (1 + ONE_TO_ONE_TOLERANCE) and apart <= (together + apart) * ONE_TO_ONE_TOLERANCE
    )


def _run(
    team: Team,
    query: dict[str, Any],
    variables: Sequence[MetricsDashboardVariable],
    *,
    timeout: float,
    start_by: float,
) -> str | None:
    """The error of the panel query, or None when it runs or was not checked.

    A transient ClickHouse failure says nothing about the panel, so it propagates and the activity retries.
    """
    started = time.monotonic()
    if started > start_by:
        return None
    try:
        runner = MetricsQueryRunner(
            query=MetricsQuery.model_validate({**query, "dateRange": DateRange(date_from=RUN_DATE_FROM)}),
            team=team,
        )
        if variables:
            runner.apply_dashboard_filters(DashboardFilter(metricVariables=list(variables)))
        with query_concurrency_slots(team):
            runner.calculate()
    except ConcurrencyLimitExceeded:
        # A busy organization says nothing about the panel, so it stays.
        logger.warning("metrics_suggested_dashboards_panel_run_skipped", team_id=team.id)
        return None
    except ExposedHogQLError as error:
        return str(error)
    except CH_TRANSIENT_ERRORS:
        raise
    except Exception:
        logger.exception("metrics_suggested_dashboards_panel_run_failed", team_id=team.id)
        return "The query could not run."
    finally:
        connections.close_all()
    if time.monotonic() - started > timeout:
        return "The query took too long to run."
    return None


def _run_in(
    context: contextvars.Context,
    team: Team,
    query: dict[str, Any],
    variables: Sequence[MetricsDashboardVariable],
    *,
    timeout: float,
    start_by: float,
) -> str | None:
    return context.run(lambda: _run(team, query, variables, timeout=timeout, start_by=start_by))


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
        count = self._value_counts.get(_attribute(attribute)) if self._value_counts is not None else None
        return count is None or count >= MIN_VARIABLE_VALUES

    def one_to_one(self, first: str, second: str) -> bool:
        if _attribute(first) == _attribute(second):
            return True
        try:
            return one_to_one(self._team, self._metric_names, first, second)
        except Exception:
            logger.warning("metrics_suggested_dashboards_variable_pair_failed", team_id=self._team.id)
            return False

    def run_errors(self, queries: Mapping[str, dict[str, Any]], variables: Sequence[dict[str, Any]]) -> dict[str, str]:
        """The error of each query that fails, with every variable set to All.

        A run counts as too slow when it takes longer than the deadline from its own start, so a panel that waits
        for a worker is not held against it. Every run finishes before this returns, so that no query of this
        generation runs on after it. ClickHouse ends each statement of a metrics query after 30 seconds.
        """
        definitions = [MetricsDashboardVariable.model_validate(variable) for variable in variables]
        start_by = time.monotonic() + RUN_BUDGET_SECONDS
        errors: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=RUN_WORKERS, thread_name_prefix="metrics-suggested-check") as executor:
            futures = {
                # Each run keeps the query tags of the activity, in its own copy of the context.
                key: executor.submit(
                    _run_in,
                    contextvars.copy_context(),
                    self._team,
                    query,
                    definitions,
                    timeout=self._deadline,
                    start_by=start_by,
                )
                for key, query in queries.items()
            }
            wait(futures.values())
            for key, future in futures.items():
                if (error := future.result()) is not None:
                    errors[key] = error
        return errors
