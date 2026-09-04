from products.growth.backend.temporal.signup_enrichment.reenrichment import (
    IcpReenrichmentSweepWorkflow,
    reenrich_organization_activity,
    report_sweep_run_activity,
    select_reenrichment_candidates_activity,
)
from products.growth.backend.temporal.signup_enrichment.rescore import (
    WizardStampRescoreWorkflow,
    resolve_wizard_rescore_signup_inputs_activity,
)
from products.growth.backend.temporal.signup_enrichment.workflow import (
    SignupEnrichmentWorkflow,
    enrich_signup_organization_activity,
)

WORKFLOWS = [SignupEnrichmentWorkflow, IcpReenrichmentSweepWorkflow, WizardStampRescoreWorkflow]

ACTIVITIES = [
    enrich_signup_organization_activity,
    select_reenrichment_candidates_activity,
    reenrich_organization_activity,
    report_sweep_run_activity,
    resolve_wizard_rescore_signup_inputs_activity,
]
