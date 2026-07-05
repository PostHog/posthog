from products.pulse.backend.temporal.activities import (
    gather_brief_inputs_activity,
    investigate_replay_patterns_activity,
    mark_brief_failed_activity,
    synthesize_brief_activity,
)
from products.pulse.backend.temporal.research_workflow import ResearchOpportunityWorkflow, research_opportunity_activity
from products.pulse.backend.temporal.workflow import GenerateProductBriefWorkflow

WORKFLOWS = [GenerateProductBriefWorkflow, ResearchOpportunityWorkflow]
ACTIVITIES = [
    gather_brief_inputs_activity,
    investigate_replay_patterns_activity,
    synthesize_brief_activity,
    mark_brief_failed_activity,
    research_opportunity_activity,
]
