from typing import TYPE_CHECKING

from products.growth.backend.temporal.signup_enrichment import (
    ACTIVITIES as SIGNUP_ENRICHMENT_ACTIVITIES,
    WORKFLOWS as SIGNUP_ENRICHMENT_WORKFLOWS,
)

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [*SIGNUP_ENRICHMENT_WORKFLOWS]

ACTIVITIES: list[ActivityDefinition] = [*SIGNUP_ENRICHMENT_ACTIVITIES]
