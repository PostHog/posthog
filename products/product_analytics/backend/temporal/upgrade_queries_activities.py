import textwrap
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


def _clause(kind: str, version: int) -> str:
    template = """
        query @? '$.** ? (
            @.kind == "{kind}" &&
            (!exists(@.version) || @.version == null || @.version < {version})
        )'"""
    return textwrap.dedent(template.format(kind=kind, version=version)).strip()


# No index serves the jsonpath clauses, so Postgres parses every row it scans.
# A bounded id window caps the rows that one statement parses.
SCAN_WINDOW_SIZE = 5_000
MAX_WINDOWS_PER_CALL = 20


@dataclasses.dataclass(frozen=True)
class GetInsightsToMigrateActivityInputs:
    """Inputs for the get insights to migrate activity."""

    batch_size: int = dataclasses.field(default=100)
    after_id: Optional[int] = dataclasses.field(default=None)
    scan_window_size: int = dataclasses.field(default=SCAN_WINDOW_SIZE)


@dataclasses.dataclass(frozen=True)
class GetInsightsToMigrateActivityResult:
    """Result of the get insights to migrate activity."""

    insight_ids: list[int]
    last_id: Optional[int]
    done: bool = False


@activity.defn
def get_insights_to_migrate(inputs: GetInsightsToMigrateActivityInputs) -> GetInsightsToMigrateActivityResult:
    _discover_migrations()  # Populate LATEST_VERSIONS; this is the first activity in the workflow

    clauses = [_clause(k, v) for k, v in sorted(LATEST_VERSIONS.items())]
    if not clauses:
        # No migrations registered — guard against emitting `WHERE ()`, which Postgres rejects
        return GetInsightsToMigrateActivityResult(insight_ids=[], last_id=inputs.after_id, done=True)

    where_body = ("\n   OR  ").join(clauses)
    sql = f"""
        SELECT id
        FROM posthog_dashboarditem
        WHERE ({where_body})
        AND id > %s AND id <= %s
        ORDER BY id
        LIMIT %s;
    """

    ids: list[int] = []
    with connection.cursor() as cur:
        cur.execute("SELECT min(id), max(id) FROM posthog_dashboarditem;")
        min_id, max_id = cur.fetchone()
        if max_id is None:
            return GetInsightsToMigrateActivityResult(insight_ids=[], last_id=inputs.after_id, done=True)

        cursor_id = inputs.after_id if inputs.after_id is not None else min_id - 1
        for _ in range(MAX_WINDOWS_PER_CALL):
            if cursor_id >= max_id:
                break
            window_end = min(cursor_id + inputs.scan_window_size, max_id)
            cur.execute(sql, [cursor_id, window_end, inputs.batch_size - len(ids)])
            ids.extend(row[0] for row in cur.fetchall())
            if len(ids) >= inputs.batch_size:
                # The window can contain more matches after the last returned id
                cursor_id = ids[-1]
                break
            cursor_id = window_end

    return GetInsightsToMigrateActivityResult(insight_ids=ids, last_id=cursor_id, done=cursor_id >= max_id)


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
