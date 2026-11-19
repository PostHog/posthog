from posthog.temporal.common.registration import ActivityDefinition

from products.growth.backend.temporal.signup_enrichment import (
    ACTIVITIES as SIGNUP_ENRICHMENT_ACTIVITIES,
    WORKFLOWS as SIGNUP_ENRICHMENT_WORKFLOWS,
)

WORKFLOWS = [*SIGNUP_ENRICHMENT_WORKFLOWS]

ACTIVITIES: list[ActivityDefinition] = [*SIGNUP_ENRICHMENT_ACTIVITIES]
