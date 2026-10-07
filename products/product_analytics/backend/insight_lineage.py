"""Keeps an insight's node in the data modeling lineage graph in step with the insight itself."""

from collections import defaultdict
from collections.abc import Collection, Iterable
from typing import TYPE_CHECKING, Any

from django.db import transaction

import structlog

from posthog.hogql.database.database import Database
from posthog.hogql.metadata import get_table_names
from posthog.hogql.parser import parse_select

from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import get_query_runner

from products.data_modeling.backend.facade.api import delete_insight_nodes, sync_insight_to_dag
from products.data_modeling.backend.facade.system_tables import DATA_MODELING_ALLOWED_SYSTEM_TABLES
from products.product_analytics.backend.facade.contracts import InsightLineageBackfill
from products.product_analytics.backend.logic import insight_display_name
from products.product_analytics.backend.models.insight import Insight
from products.warehouse_sources.backend.facade.api import resolve_object_by_name

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)

_WRAPPER_KINDS = frozenset({"DataTableNode", "DataVisualizationNode", "BIVisualizationNode", "InsightVizNode"})


def _names_a_table(value: object) -> bool:
    """Whether any node in a query carries a `table_name`, the field every data warehouse series uses."""
    if isinstance(value, dict):
        table_name = value.get("table_name")
        if isinstance(table_name, str) and table_name:
            return True
        return any(_names_a_table(child) for child in value.values())
    if isinstance(value, list):
        return any(_names_a_table(child) for child in value)
    return False


def insight_table_names(team: "Team", query: dict[str, Any]) -> set[str]:
    """Every table and view an insight's query reads, spelled the way the query spells it.

    SQL is parsed and not resolved, because resolution replaces a view with its body and the view's
    name is the dependency. Every other kind gets its HogQL from its runner's `to_query()`, which is
    where a data warehouse series turns into a table name. A query with no `table_name` anywhere reads
    only PostHog tables, so building its runner can find nothing the caller keeps.
    """
    source = query.get("source") if query.get("kind") in _WRAPPER_KINDS else query
    if isinstance(source, dict) and source.get("kind") == "HogQLQuery":
        return set(get_table_names(parse_select(source["query"])))
    if not _names_a_table(query):
        return set()
    return set(get_table_names(get_query_runner(query, team).to_query()))


def warehouse_dependency_names(team: "Team", query: dict[str, Any]) -> list[str]:
    """The warehouse tables and views an insight reads.

    PostHog tables such as `events` and `persons` are left out. Nearly every insight reads them, so
    edges to them would join every insight to the same few nodes and the graph would show nothing.
    """
    return sorted(
        name for name in insight_table_names(team, query) if resolve_object_by_name(team.pk, name) is not None
    )


def _lineage_database(team: "Team") -> Database:
    # No user runs the sync, so warehouse access control must not hide a table the insight reads.
    return Database.create_for(
        team=team, bypass_warehouse_access_control=True, allowed_system_tables=DATA_MODELING_ALLOWED_SYSTEM_TABLES
    )


def sync_insight_lineage(insight: Insight, databases: dict[int, Database] | None = None) -> bool:
    """Bring the insight's lineage node in line with the insight, best effort. Returns False on a failure.

    A lineage failure must never fail the insight save, so every error is caught and the node keeps
    the edges it had. That is the safer way to fail: a stale edge can make a view delete name an
    insight that no longer reads the view, but a missing edge lets the delete go through and break
    the insight. The savepoint keeps a database error here from aborting the caller's transaction.

    `databases` holds one schema per team for a caller syncing many insights. A schema is built only
    for an insight that reads a warehouse table or view, because building it is the expensive part.
    """
    try:
        with transaction.atomic():
            if insight.deleted:
                delete_insight_nodes(insight.team_id, [insight.pk])
                return True
            dependency_names = warehouse_dependency_names(insight.team, insight.query or {})
            database = None
            if dependency_names and databases is not None:
                if insight.team_id not in databases:
                    databases[insight.team_id] = _lineage_database(insight.team)
                database = databases[insight.team_id]
            sync_insight_to_dag(
                insight.team,
                insight.pk,
                insight.short_id,
                insight_display_name(insight),
                dependency_names,
                database=database,
            )
    except Exception as error:
        capture_exception(error)
        logger.exception("Failed to sync insight lineage", insight_id=insight.pk, team_id=insight.team_id)
        return False
    return True


def remove_insight_lineage(insights: Collection[Insight]) -> None:
    """Drop the lineage nodes of insights that were just deleted, best effort.

    A node left behind does not block a view delete, because the dependents check reads the insight
    row, so a failure here must not turn a successful delete into an error.
    """
    insight_ids_by_team: dict[int, list[int]] = defaultdict(list)
    for insight in insights:
        insight_ids_by_team[insight.team_id].append(insight.pk)
    try:
        with transaction.atomic():
            for team_id, insight_ids in insight_ids_by_team.items():
                delete_insight_nodes(team_id, insight_ids)
    except Exception as error:
        capture_exception(error)
        logger.exception("Failed to remove insight lineage", insight_ids=[insight.pk for insight in insights])


def sync_insights_lineage(insights: Iterable[Insight]) -> InsightLineageBackfill:
    """Bring the lineage nodes of many insights in line, building each team's schema at most once."""
    databases: dict[int, Database] = {}
    seen = 0
    failed = 0
    for insight in insights:
        seen += 1
        if not sync_insight_lineage(insight, databases):
            failed += 1
    return InsightLineageBackfill(seen=seen, failed=failed)


def sync_team_insight_lineage(team_id: int, chunk_size: int) -> InsightLineageBackfill:
    insights = Insight.objects.filter(team_id=team_id).select_related("team").order_by("id")
    return sync_insights_lineage(insights.iterator(chunk_size=chunk_size))
