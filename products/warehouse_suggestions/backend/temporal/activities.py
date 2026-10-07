from collections import Counter
from itertools import batched

from django.utils import timezone

from temporalio import activity

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.execute import KillSwitchLevel, get_kill_switch_level
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.warehouse_object_reads import WAREHOUSE_OBJECT_READS_DAILY_TABLE
from posthog.models.team import Team
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.rollout import filter_ids_for_rollout

from ..logic.flags import is_warehouse_suggestions_enabled
from ..logic.job import TeamRunStatus, run_team
from ..logic.reads import ReadWindow, read_rollup_days
from ..logic.rules import RULES
from .contracts import BatchOutcome, WarehouseSuggestionsInputs

LOGGER = get_logger(__name__)
FULL_ROLLOUT = 1.0

TEAMS_WITH_READS_SQL = f"""
SELECT DISTINCT team_id
FROM {WAREHOUSE_OBJECT_READS_DAILY_TABLE}
WHERE day >= today() - %(window_days)s
"""


def team_batches(inputs: WarehouseSuggestionsInputs) -> list[list[int]]:
    if get_kill_switch_level() != KillSwitchLevel.OFF:
        LOGGER.info("warehouse_suggestions.skipped_by_kill_switch")
        return []
    candidate_ids = inputs.team_ids if inputs.team_ids is not None else _teams_with_reads()
    teams = (
        Team.objects.filter(
            id__in=candidate_ids, is_demo=False, parent_team__isnull=True, organization__for_internal_metrics=False
        )
        .select_related("organization")
        .order_by("id")
    )
    team_ids = [team.pk for team in teams if is_warehouse_suggestions_enabled(team)]
    if inputs.rollout_percentage < FULL_ROLLOUT:
        team_ids = filter_ids_for_rollout(team_ids, inputs.rollout_percentage)
    return [list(batch) for batch in batched(team_ids, inputs.batch_size, strict=False)]


def run_batch(team_ids: list[int], run_id: str) -> BatchOutcome:
    today = timezone.now().date()
    rollup_days = read_rollup_days(ReadWindow.ending(today, RULES))
    outcomes: Counter[str] = Counter()
    for team_id in team_ids:
        try:
            outcomes[run_team(team_id, run_id=run_id, today=today, rollup_days=rollup_days).status] += 1
        except Exception:
            LOGGER.exception("warehouse_suggestions.team_failed", team_id=team_id)
            outcomes["failed"] += 1
    return BatchOutcome(
        processed=outcomes[TeamRunStatus.PROCESSED],
        not_eligible=outcomes[TeamRunStatus.NOT_ELIGIBLE],
        disabled=outcomes[TeamRunStatus.DISABLED],
        failed=outcomes["failed"],
    )


def _teams_with_reads() -> list[int]:
    tag_queries(product=Product.WAREHOUSE, feature=Feature.ENRICHMENT, name="warehouse_suggestions_teams")
    return [team_id for (team_id,) in sync_execute(TEAMS_WITH_READS_SQL, {"window_days": RULES.window_days})]


@activity.defn
async def get_warehouse_suggestion_team_batches(inputs: WarehouseSuggestionsInputs) -> list[list[int]]:
    return await database_sync_to_async_pool(team_batches)(inputs)


@activity.defn
async def generate_warehouse_suggestions(team_ids: list[int], run_id: str) -> BatchOutcome:
    async with Heartbeater():
        return await database_sync_to_async_pool(run_batch)(team_ids, run_id)
