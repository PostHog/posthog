"""Per-metric query counts, so that a team can see which metrics its queries read and which they never read."""

import datetime as dt
from collections.abc import Iterable
from uuid import UUID

from django.db import DatabaseError, connections, router, transaction
from django.db.models import Max, Sum
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.metrics.backend.facade.contracts import DEFAULT_QUERY_COUNT_DAYS, MetricQueryCount
from products.metrics.backend.models import MetricDailyQueryCount

logger = structlog.get_logger(__name__)

_MAX_METRIC_NAME_LENGTH = MetricDailyQueryCount._meta.get_field("metric_name").max_length or 0


def record_metric_queries(team: Team, metric_names: Iterable[str]) -> None:
    """Count one query for each distinct metric name. A failure is logged and never reaches the query."""
    # Sorted, so that two concurrent upserts lock the rows of a team in the same order and cannot deadlock.
    names = sorted({name for name in metric_names if name and len(name) <= _MAX_METRIC_NAME_LENGTH})
    if not names:
        return
    # The model is scoped to the root team, so the rows of an environment belong to its parent team.
    team_id = team.parent_team_id or team.pk
    now = timezone.now()
    table = MetricDailyQueryCount._meta.db_table  # Trusted: from Django ORM metadata
    values = ", ".join(["(%s, %s, %s, %s, 1, %s)"] * len(names))
    params: list[UUID | int | str | dt.date | dt.datetime] = []
    for name in names:
        params.extend([MetricDailyQueryCount._meta.pk.get_default(), team_id, name, now.date(), now])
    # One statement adds to the row of the day or creates it, so concurrent queries do not lose counts.
    sql = f"""
        INSERT INTO {table} (id, team_id, metric_name, date, query_count, last_queried_at)
        VALUES {values}
        ON CONFLICT (team_id, metric_name, date) DO UPDATE SET
            query_count = {table}.query_count + EXCLUDED.query_count,
            last_queried_at = GREATEST({table}.last_queried_at, EXCLUDED.last_queried_at)
    """
    using = router.db_for_write(MetricDailyQueryCount)
    try:
        # The savepoint keeps a failed write from breaking a transaction that the caller holds open.
        with transaction.atomic(using=using), connections[using].cursor() as cursor:
            cursor.execute(sql, params)
    except DatabaseError as error:
        logger.warning("metric_query_count_write_failed", team_id=team_id, metric_count=len(names))
        capture_exception(error)


def record_promql_query(team: Team, expr: str) -> None:
    """Count one query for each metric that a PromQL expression selects."""
    # promql_text imports the promql module, which imports this module, so a module-level import is circular.
    from products.metrics.backend.dashboard_import.promql_text import metric_names  # noqa: PLC0415

    record_metric_queries(team, metric_names(expr))


def list_metric_query_counts(
    team: Team, *, days: int = DEFAULT_QUERY_COUNT_DAYS, limit: int = 100
) -> list[MetricQueryCount]:
    """The query counts of the last `days` UTC days, today included, with the most queried metric first."""
    since = timezone.now().date() - dt.timedelta(days=days - 1)
    rows = (
        MetricDailyQueryCount.objects.for_team(team.parent_team_id or team.pk, canonical=True)
        .filter(date__gte=since)
        .values("metric_name")
        .annotate(total=Sum("query_count"), last=Max("last_queried_at"))
        .order_by("-total", "metric_name")[:limit]
    )
    return [
        MetricQueryCount(metric_name=row["metric_name"], query_count=row["total"], last_queried_at=row["last"])
        for row in rows
    ]
