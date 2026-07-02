from products.pulse.backend.temporal.activities import gather_brief_inputs_activity, synthesize_brief_activity
from products.pulse.backend.temporal.workflow import GenerateProductBriefWorkflow

WORKFLOWS = [GenerateProductBriefWorkflow]
ACTIVITIES = [gather_brief_inputs_activity, synthesize_brief_activity]
