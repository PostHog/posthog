from products.growth.backend.temporal.signup_enrichment.workflow import (
    SignupEnrichmentWorkflow,
    enrich_signup_organization_activity,
)

WORKFLOWS = [SignupEnrichmentWorkflow]

ACTIVITIES = [enrich_signup_organization_activity]
