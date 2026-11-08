from datetime import datetime, timedelta
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.models import Team

from products.error_tracking.backend.models import ErrorTrackingIssue

# Bounds the query text (ClickHouse caps it at 1 MiB) and the rows one query returns.
_CANDIDATE_CHUNK_SIZE = 5000


def find_auto_resolve_candidates(team: Team, after_days: int) -> list[UUID]:
    """Return the ids of the team's active issues that had no exception and no change in the last `after_days` days."""
    cutoff = timezone.now() - timedelta(days=after_days)
    candidate_ids = list(
        ErrorTrackingIssue.objects.filter(
            team_id=team.pk, status=ErrorTrackingIssue.Status.ACTIVE, created_at__lt=cutoff
        )
        .filter(Q(state_updated_at__isnull=True) | Q(state_updated_at__lt=cutoff))
        .values_list("id", flat=True)
    )
    recent: set[UUID] = set()
    for start in range(0, len(candidate_ids), _CANDIDATE_CHUNK_SIZE):
        recent |= _issues_with_exceptions_since(team, cutoff, candidate_ids[start : start + _CANDIDATE_CHUNK_SIZE])
    return [issue_id for issue_id in candidate_ids if issue_id not in recent]


def _issues_with_exceptions_since(team: Team, cutoff: datetime, issue_ids: list[UUID]) -> set[UUID]:
    # Ask for issues with recent exceptions, never for issues whose last exception is old: an issue past event
    # retention has no rows at all and must still count as quiet. Ingestion lag can hide an exception that
    # arrived just now, so an issue can resolve right after it recurs; the next exception reopens it.
    tag_queries(product=Product.ERROR_TRACKING, team_id=team.pk, name="auto_resolve:recent_issues")
    response = execute_hogql_query(
        query="""
            SELECT DISTINCT issue_id
            FROM events
            WHERE event = '$exception'
            AND timestamp >= {cutoff}
            AND issue_id IN {issue_ids}
            LIMIT {limit}
        """,
        team=team,
        placeholders={
            "cutoff": ast.Constant(value=cutoff),
            "issue_ids": ast.Tuple(exprs=[ast.Constant(value=str(issue_id)) for issue_id in issue_ids]),
            "limit": ast.Constant(value=len(issue_ids)),
        },
        workload=Workload.OFFLINE,
        ch_user=ClickHouseUser.ERROR_TRACKING,
    )
    return {UUID(str(row[0])) for row in response.results or []}
