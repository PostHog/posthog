from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from posthog.hogql.ast import Constant
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

if TYPE_CHECKING:
    from posthog.models import Team

TOP_HEATMAP_PAGES_LIMIT = 20
TOP_HEATMAP_PAGES_DAYS = 30


def top_heatmap_pages(team: "Team") -> list[dict[str, Any]]:
    since = timezone.now() - timedelta(days=TOP_HEATMAP_PAGES_DAYS)
    stmt = parse_select(
        "SELECT current_url AS url, count() AS cnt FROM heatmaps "
        "WHERE timestamp >= {since} AND current_url != '' "
        "GROUP BY current_url ORDER BY cnt DESC LIMIT {limit}",
        placeholders={"since": Constant(value=since), "limit": Constant(value=TOP_HEATMAP_PAGES_LIMIT)},
    )
    result = execute_hogql_query(
        query=stmt, team=team, limit_context=LimitContext.HEATMAPS, context=HogQLContext(team_id=team.pk)
    )
    return [{"url": row[0], "count": row[1]} for row in result.results]
