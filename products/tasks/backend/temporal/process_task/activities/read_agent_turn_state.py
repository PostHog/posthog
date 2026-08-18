from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.utils import asyncify, close_db_connections

from products.tasks.backend.logic.services.agent_command import read_agent_turn_in_flight
from products.tasks.backend.models import TaskRun

from .get_task_processing_context import TaskProcessingContext


@frozen
class ReadAgentTurnStateInput:
    context: TaskProcessingContext


@frozen
class ReadAgentTurnStateOutput:
    turn_in_flight: bool | None = None


@activity.defn
@asyncify
@close_db_connections
def read_agent_turn_state(input: ReadAgentTurnStateInput) -> ReadAgentTurnStateOutput:
    task_run = TaskRun.objects.filter(id=input.context.run_id).first()
    if task_run is None:
        return ReadAgentTurnStateOutput()
    return ReadAgentTurnStateOutput(turn_in_flight=read_agent_turn_in_flight(task_run))
