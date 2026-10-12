"""Checks that a panel query is valid and runs, before the import puts it on a dashboard."""

from __future__ import annotations

import re
import datetime as dt
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, wait

from django.db import connections
from django.utils import timezone

import structlog

from posthog.schema import DateRange, HogLanguage, HogQLFilters, HogQLMetadata

from posthog.hogql.metadata import get_hogql_metadata

from posthog.dataclasses import frozen
from posthog.models import Team

from products.metrics.backend.dashboard_import.catalog import HISTOGRAM_TYPES, MetricCatalog
from products.metrics.backend.dashboard_import.promql_text import metric_names
from products.metrics.backend.dashboard_import.spec import BuilderClause, BuilderQuery, PanelQuery
from products.metrics.backend.facade.contracts import MetricFilter, MetricGroupBy, MetricQueryClause, MetricQueryRequest
from products.metrics.backend.facade.enums import FilterOp, MetricAggregation, MetricType
from products.metrics.backend.formula import parse_formula
from products.metrics.backend.promql import PromQLQueryError, run_promql_range

logger = structlog.get_logger(__name__)

SMOKE_WINDOW = dt.timedelta(minutes=15)
SMOKE_WORKERS = 8
MAX_ERROR_LENGTH = 400
# The p95 aggregation of the builder is the quantile aggregation of the engine at the 95th percentile.
P95_QUANTILE = 0.95
LOGS_AND_TRACES_TABLES = frozenset(
    {"logs", "posthog.logs", "trace_spans", "posthog.trace_spans", "posthog.trace_attributes"}
)
_FILTERS_PLACEHOLDER = re.compile(r"\{\s*filters\s*\}")
NO_DATA_NOTE = "The query returned no data in the last 15 minutes."


@frozen
class QueryCheck:
    ok: bool
    error: str | None = None
    notes: tuple[str, ...] = ()
    # Set when the run did not finish in time. The import then lets the agent decide, not the check.
    timed_out: bool = False


def _trim(message: str) -> str:
    return message if len(message) <= MAX_ERROR_LENGTH else f"{message[: MAX_ERROR_LENGTH - 1]}…"


def _failure(message: str) -> QueryCheck:
    return QueryCheck(ok=False, error=_trim(message))


class PanelValidator:
    def __init__(self, *, team: Team, catalog: MetricCatalog, promql_available: bool) -> None:
        self._team = team
        self._catalog = catalog
        self._promql_available = promql_available

    def check_all(self, queries: Mapping[str, PanelQuery], *, deadline_seconds: float) -> dict[str, QueryCheck]:
        """Check every query. PromQL queries run in parallel and get `deadline_seconds` in total."""
        results: dict[str, QueryCheck] = {}
        smoke_runs: dict[str, str] = {}
        for key, query in queries.items():
            static = self._static_check(query)
            if static is not None:
                results[key] = static
            elif query.language == "promql" and query.promql:
                smoke_runs[key] = query.promql
            else:
                results[key] = QueryCheck(ok=True)
        if not smoke_runs:
            return results
        executor = ThreadPoolExecutor(max_workers=SMOKE_WORKERS, thread_name_prefix="metrics-import-check")
        try:
            futures = {key: executor.submit(self._smoke_run, expr) for key, expr in smoke_runs.items()}
            wait(futures.values(), timeout=deadline_seconds)
            for key, future in futures.items():
                if future.done():
                    results[key] = future.result()
                else:
                    future.cancel()
                    results[key] = QueryCheck(ok=False, error="The query took too long to check.", timed_out=True)
        finally:
            # A run that is still in flight finishes in the background. It does not hold up the response.
            executor.shutdown(wait=False, cancel_futures=True)
        return results

    def _static_check(self, query: PanelQuery) -> QueryCheck | None:
        """A failure, a success for a query that needs no run, or None when the query needs a PromQL run."""
        if query.language == "promql":
            if not self._promql_available:
                return _failure("PromQL is not available in this project. Use builder clauses.")
            if not query.promql or not query.promql.strip():
                return _failure("The PromQL expression is empty.")
            unknown = [name for name in metric_names(query.promql) if self._catalog.resolve(name) is None]
            if unknown:
                return _failure(f"These metrics do not exist in this project: {', '.join(unknown)}.")
            return None
        if query.language == "builder":
            return self._check_builder(query.builder)
        if query.language == "histogram":
            entry = self._catalog.resolve(query.histogram_metric or "")
            if entry is None:
                return _failure(f'The metric "{query.histogram_metric}" does not exist in this project.')
            if entry.metric_type not in HISTOGRAM_TYPES:
                return _failure(f'The metric "{entry.name}" is a {entry.metric_type}, not a histogram.')
            return QueryCheck(ok=True)
        return self._check_hogql(query.hogql or "")

    def _check_builder(self, builder: BuilderQuery | None) -> QueryCheck:
        if builder is None or not builder.clauses:
            return _failure("The builder query has no clauses.")
        unknown = [
            clause.metric_name for clause in builder.clauses if self._catalog.resolve(clause.metric_name) is None
        ]
        if unknown:
            return _failure(f"These metrics do not exist in this project: {', '.join(unknown)}.")
        now = timezone.now()
        try:
            request = MetricQueryRequest(
                clauses=tuple(self.clause_contract(clause) for clause in builder.clauses),
                date_from=now - SMOKE_WINDOW,
                date_to=now,
                formula=builder.formula or None,
            )
            if request.formula is not None:
                parse_formula(request.formula, frozenset(clause.name for clause in request.clauses))
        except ValueError as error:
            return _failure(str(error))
        return QueryCheck(ok=True)

    def clause_contract(self, clause: BuilderClause) -> MetricQueryClause:
        entry = self._catalog.resolve(clause.metric_name)
        if clause.aggregation == "p95":
            aggregation, quantile = MetricAggregation.QUANTILE, P95_QUANTILE
        else:
            aggregation = MetricAggregation(clause.aggregation)
            quantile = clause.quantile if aggregation == MetricAggregation.HISTOGRAM_QUANTILE else None
        return MetricQueryClause(
            name=clause.name,
            metric_name=clause.metric_name,
            aggregation=aggregation,
            filters=tuple(
                MetricFilter(key=item.key, op=FilterOp(item.op), value=item.value) for item in clause.filters
            ),
            group_by=tuple(MetricGroupBy(key=key) for key in clause.group_by),
            quantile=quantile,
            metric_type=MetricType(entry.metric_type) if entry and entry.metric_type in MetricType else None,
        )

    def _check_hogql(self, sql: str) -> QueryCheck:
        if not sql.strip():
            return _failure("The SQL query is empty.")
        if not _FILTERS_PLACEHOLDER.search(sql):
            return _failure("Add {filters} to the WHERE clause, so that the dashboard date range applies.")
        response = get_hogql_metadata(
            HogQLMetadata(
                language=HogLanguage.HOG_QL, query=sql, filters=HogQLFilters(dateRange=DateRange(date_from="-1h"))
            ),
            self._team,
        )
        if not response.isValid:
            return _failure("; ".join(error.message for error in response.errors) or "The SQL query is not valid.")
        tables = set(response.table_names or [])
        if not tables or not tables <= LOGS_AND_TRACES_TABLES:
            return _failure("A SQL panel can read only the logs and posthog.trace_spans tables.")
        return QueryCheck(ok=True)

    def _smoke_run(self, expr: str) -> QueryCheck:
        try:
            now = timezone.now()
            series = run_promql_range(self._team, expr, now - SMOKE_WINDOW, now, None)
        except PromQLQueryError as error:
            return _failure(str(error))
        except Exception:
            logger.exception("metrics_dashboard_import_smoke_run_failed", team_id=self._team.pk)
            return _failure("The query could not run. Try again later.")
        finally:
            connections.close_all()
        has_data = any(point.value is not None for item in series for point in item.points)
        return QueryCheck(ok=True, notes=() if has_data else (NO_DATA_NOTE,))
