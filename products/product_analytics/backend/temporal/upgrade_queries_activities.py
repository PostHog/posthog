import dataclasses
from typing import Any, Optional, cast

from django.db import connection

from structlog import get_logger
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.schema_migrations import LATEST_VERSIONS, _discover_migrations
from posthog.schema_migrations.upgrade import upgrade

from products.product_analytics.backend.facade.models import Insight

LOGGER = get_logger(__name__)


def _stale_schema_stamps(latest_versions: dict[str, int]) -> list[str]:
    """Every `kind:version` stamp that the registry considers out of date.

    `posthog_dashboarditem_schema_versions` stamps a node with no version, or a null one, as
    version 0, so enumerating 0 to latest - 1 per kind covers every stale node.
    """
    return [f"{kind}:{version}" for kind, latest in sorted(latest_versions.items()) for version in range(latest)]


@dataclasses.dataclass(frozen=True)
class GetInsightsToMigrateActivityInputs:
    """Inputs for the get insights to migrate activity."""

    batch_size: int = dataclasses.field(default=100)
    after_id: Optional[int] = dataclasses.field(default=None)


@dataclasses.dataclass(frozen=True)
class GetInsightsToMigrateActivityResult:
    """Result of the get insights to migrate activity."""

    insight_ids: list[int]
    last_id: Optional[int]


@activity.defn
def get_insights_to_migrate(inputs: GetInsightsToMigrateActivityInputs) -> GetInsightsToMigrateActivityResult:
    _discover_migrations()  # Populate LATEST_VERSIONS; this is the first activity in the workflow

    stamps = _stale_schema_stamps(LATEST_VERSIONS)
    if not stamps:
        return GetInsightsToMigrateActivityResult(insight_ids=[], last_id=inputs.after_id)

    params: dict[str, Any] = {"stamps": stamps, "limit": inputs.batch_size}
    after_clause = ""
    if inputs.after_id is not None:
        after_clause = "AND id > %(after_id)s"
        params["after_id"] = inputs.after_id

    sql = f"""
        SELECT id
        FROM posthog_dashboarditem
        WHERE posthog_dashboarditem_schema_versions(query) && %(stamps)s::text[]
        {after_clause}
        ORDER BY id
        LIMIT %(limit)s;
    """

    with connection.cursor() as cur:
        cur.execute(sql, params)
        ids = [row[0] for row in cur.fetchall()]
    last_id = ids[-1] if ids else inputs.after_id

    return GetInsightsToMigrateActivityResult(insight_ids=ids, last_id=last_id)


@dataclasses.dataclass(frozen=True)
class MigrateInsightsBatchActivityInputs:
    """Inputs for the migrate insights batch activity."""

    insight_ids: list[int] = dataclasses.field()


@activity.defn
def migrate_insights_batch(inputs: MigrateInsightsBatchActivityInputs) -> list[int]:
    """Migrate a batch of insights to the latest version."""
    logger = LOGGER.bind()
    failed: list[int] = []

    insights = Insight.objects_including_soft_deleted.filter(id__in=inputs.insight_ids)

    for insight in insights:
        try:
            insight.query = upgrade(cast(dict[Any, Any], insight.query))
            # Narrow write: a full save would clobber concurrent user edits to other fields with
            # the stale values read above. Insight.save() appends query_metadata when regenerated.
            insight.save(update_fields=["query"])
        except Exception as e:
            logger.exception(f"Error migrating insight {insight.id}: {str(e)}")
            capture_exception(e, {"insight_id": insight.id, "team_id": insight.team_id})
            failed.append(insight.id)

    return failed
