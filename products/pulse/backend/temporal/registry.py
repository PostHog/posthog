from products.pulse.backend.temporal.activities import (
    gather_brief_inputs_activity,
    mark_brief_failed_activity,
    mark_brief_quiet_activity,
    prepare_mission_activity,
    run_agent_activity,
    synthesize_brief_activity,
    validate_and_persist_activity,
)
from products.pulse.backend.temporal.workflow import GenerateProductBriefWorkflow

WORKFLOWS = [GenerateProductBriefWorkflow]
ACTIVITIES = [
    gather_brief_inputs_activity,
    synthesize_brief_activity,
    prepare_mission_activity,
    run_agent_activity,
    validate_and_persist_activity,
    mark_brief_quiet_activity,
    mark_brief_failed_activity,
]
