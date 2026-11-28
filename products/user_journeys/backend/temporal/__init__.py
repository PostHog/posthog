from products.user_journeys.backend.temporal.stale_runs import (
    ReapStaleJourneyRunsWorkflow,
    reap_stale_journey_runs_activity,
)

WORKFLOWS = [ReapStaleJourneyRunsWorkflow]
ACTIVITIES = [reap_stale_journey_runs_activity]
