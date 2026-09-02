from products.growth.backend.temporal.signup_enrichment.harmonic_status_poll import (
    HarmonicEnrichmentStatusPollWorkflow,
    poll_status_batch_activity,
    report_status_poll_run_activity,
    select_status_poll_candidates_activity,
)
from products.growth.backend.temporal.signup_enrichment.reenrichment import (
    IcpReenrichmentSweepWorkflow,
    reenrich_organization_activity,
    report_sweep_run_activity,
    select_reenrichment_candidates_activity,
)
from products.growth.backend.temporal.signup_enrichment.workflow import (
    SignupEnrichmentWorkflow,
    enrich_signup_organization_activity,
)

WORKFLOWS = [SignupEnrichmentWorkflow, IcpReenrichmentSweepWorkflow, HarmonicEnrichmentStatusPollWorkflow]

ACTIVITIES = [
    enrich_signup_organization_activity,
    select_reenrichment_candidates_activity,
    reenrich_organization_activity,
    report_sweep_run_activity,
    select_status_poll_candidates_activity,
    poll_status_batch_activity,
    report_status_poll_run_activity,
]
