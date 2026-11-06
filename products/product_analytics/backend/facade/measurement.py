from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.models import Team, User
from posthog.schema_migrations.upgrade import upgrade

from products.product_analytics.backend.chart_events import chart_events

from .api import saved_insight_for_read
from .contracts import InsightDeliveryEvidence


def insight_delivery_evidence(
    *, team: Team, user: User, short_id: str, workload: Workload, since: datetime | None = None
) -> InsightDeliveryEvidence | None:
    insight = saved_insight_for_read(team=team, user=user, short_id=short_id)
    with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.INSIGHT, team_id=team.id, user_id=user.id):
        events = chart_events(upgrade(insight.query), team, user) if insight else None
        if events is None:
            return None
        where: ast.Expr = events.where
        if since is not None:
            where = ast.And(
                exprs=[
                    events.where,
                    ast.CompareOperation(
                        left=events.timestamp(), op=ast.CompareOperationOp.GtEq, right=ast.Constant(value=since)
                    ),
                ]
            )
        query = events.select(
            "SELECT count(), uniqExact({person}), min({timestamp}), max({timestamp}), groupUniqArray(100)({event}) FROM events",
            where=where,
            person=ast.Field(chain=[events.alias, "distinct_id"] if events.alias else ["distinct_id"]),
            timestamp=events.timestamp(),
            event=ast.Field(chain=[events.alias, "event"] if events.alias else ["event"]),
        )
        result = execute_hogql_query(
            query=query,
            team=team,
            user=user,
            query_type="insight_delivery_evidence",
            modifiers=events.modifiers,
            context=HogQLContext(team_id=team.id, user=user, database=events.database),
            workload=workload,
        )
    rows = result.results or []
    if not rows:
        return None
    count, people, first, last, names = rows[0]
    return InsightDeliveryEvidence(
        events=int(count),
        participants=int(people),
        first_event_at=first if count else None,
        last_event_at=last if count else None,
        window_start=max(events.date_from, since) if since else events.date_from,
        window_end=events.date_to,
        event_names=tuple(names),
    )
