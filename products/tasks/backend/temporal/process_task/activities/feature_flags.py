from dataclasses import dataclass
from typing import Any

from temporalio import activity

from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections

logger = get_logger(__name__)


@dataclass
class IsSlackAppAgentDesignEnabledForTaskActivityInput:
    integration_id: int
    run_id: str


AGENT_DESIGN_STATE_KEY = "slack_app_agent_design_enabled"


@activity.defn
@close_db_connections
def is_slack_app_agent_design_enabled_for_task_activity(
    input: IsSlackAppAgentDesignEnabledForTaskActivityInput,
) -> bool:
    """Flag check + persist to TaskRun.state so out-of-workflow callers (e.g.
    forward_pending_message) can read the decision without re-evaluating."""
    from products.slack_app.backend.feature_flags import is_slack_app_agent_design_enabled
    from products.tasks.backend.models import TaskRun

    run = TaskRun.objects.select_related("task__created_by").filter(id=input.run_id).first()
    try:
        if run is None:
            raise IntegrationNotFound(f"No task run {input.run_id}")
        integration = IntegrationManager.slack.oauth.get(run.team_id, input.integration_id)
    except IntegrationNotFound:
        logger.warning("slack_app_agent_design_integration_missing", integration_id=input.integration_id)
        enabled = False
    else:
        # The run's creator is the person the decision is about, so the gate resolves the
        # flag against them and an internal rollout can name people by email or cohort the
        # way every other one does. None when the run has no creator on record.
        creator = run.task.created_by
        enabled = is_slack_app_agent_design_enabled(integration, creator.distinct_id if creator else None)

    def _persist(state: dict[str, Any]) -> None:
        state[AGENT_DESIGN_STATE_KEY] = enabled

    try:
        TaskRun.mutate_state_atomic(input.run_id, _persist)
    except Exception:
        logger.exception("slack_app_agent_design_state_persist_failed", run_id=input.run_id)
    return enabled
