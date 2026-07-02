from dataclasses import dataclass
from typing import Any

from temporalio import activity

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

    enabled = is_slack_app_agent_design_enabled(input.integration_id)

    def _persist(state: dict[str, Any]) -> None:
        state[AGENT_DESIGN_STATE_KEY] = enabled

    try:
        TaskRun.mutate_state_atomic(input.run_id, _persist)
    except Exception:
        logger.exception("slack_app_agent_design_state_persist_failed", run_id=input.run_id)
    return enabled
