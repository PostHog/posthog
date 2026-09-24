from django.db import close_old_connections

import structlog
from temporalio import activity

from products.error_tracking.backend.logic.auto_resolve import auto_resolve_team, get_auto_resolve_team_settings
from products.error_tracking.backend.temporal.auto_resolve.types import (
    AutoResolveBatchInputs,
    AutoResolveBatchResult,
    AutoResolveInputs,
    TeamAutoResolveConfig,
)

logger = structlog.get_logger(__name__)


@activity.defn
def get_auto_resolve_team_batches_activity(inputs: AutoResolveInputs) -> list[list[TeamAutoResolveConfig]]:
    close_old_connections()

    teams = [
        TeamAutoResolveConfig(team_id=setting.team_id, days=setting.days)
        for setting in get_auto_resolve_team_settings()
    ]
    batches = [teams[i : i + inputs.batch_size] for i in range(0, len(teams), inputs.batch_size)]
    logger.info("error_tracking.auto_resolve.teams_enumerated", team_count=len(teams), batch_count=len(batches))
    return batches


@activity.defn
def auto_resolve_batch_activity(inputs: AutoResolveBatchInputs) -> AutoResolveBatchResult:
    close_old_connections()

    teams_processed = 0
    teams_failed = 0
    issues_resolved = 0
    for team in inputs.teams:
        activity.heartbeat(team.team_id)
        # One team's failure must not stop the rest of the batch; it gets retried on the next daily run.
        try:
            issues_resolved += auto_resolve_team(team.team_id)
            teams_processed += 1
        except Exception:
            teams_failed += 1
            logger.exception("error_tracking.auto_resolve.team_failed", team_id=team.team_id)

    return AutoResolveBatchResult(
        teams_processed=teams_processed, teams_failed=teams_failed, issues_resolved=issues_resolved
    )
