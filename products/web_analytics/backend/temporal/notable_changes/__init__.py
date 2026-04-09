from products.web_analytics.backend.temporal.notable_changes.activities import get_eligible_team_ids, process_team_batch
from products.web_analytics.backend.temporal.notable_changes.workflows import WebNotableChangesCoordinatorWorkflow

WORKFLOWS = [
    WebNotableChangesCoordinatorWorkflow,
]

ACTIVITIES = [
    get_eligible_team_ids,
    process_team_batch,
]
