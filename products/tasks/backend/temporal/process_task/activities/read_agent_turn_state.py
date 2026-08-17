from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import asyncify, close_db_connections

from products.tasks.backend.logic.services.agent_command import read_agent_turn_in_flight
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.observability import log_activity_execution

from .get_task_processing_context import TaskProcessingContext

logger = get_logger(__name__)


@frozen
class ReadAgentTurnStateInput:
    context: TaskProcessingContext


@frozen
class ReadAgentTurnStateOutput:
    # None when the sandbox could not answer, kept distinct from False so the caller can treat
    # "no" and "don't know" differently.
    turn_in_flight: bool | None = None


@activity.defn
@asyncify
@close_db_connections
def read_agent_turn_state(input: ReadAgentTurnStateInput) -> ReadAgentTurnStateOutput:
    """Ask the sandbox whether its agent is part-way through a turn.

    The workflow calls this when the inactivity window closes, to tell a finished agent from one
    that is working without saying so. Inferring it from the event stream cannot work, because
    anything the agent-server emits to prove it is alive re-arms that window. This reads a route
    that logs nothing.
    """
    ctx = input.context
    with log_activity_execution("read_agent_turn_state", **ctx.to_log_context()):
        task_run = TaskRun.objects.filter(id=ctx.run_id).first()
        if task_run is None:
            logger.warning("read_agent_turn_state_run_missing", run_id=ctx.run_id)
            return ReadAgentTurnStateOutput()
        return ReadAgentTurnStateOutput(turn_in_flight=read_agent_turn_in_flight(task_run))
