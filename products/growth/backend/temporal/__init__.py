from products.growth.backend.temporal.account_audit import (
    ACTIVITIES as ACCOUNT_AUDIT_ACTIVITIES,
    WORKFLOWS as ACCOUNT_AUDIT_WORKFLOWS,
)
from products.growth.backend.temporal.signup_enrichment import (
    ACTIVITIES as SIGNUP_ENRICHMENT_ACTIVITIES,
    WORKFLOWS as SIGNUP_ENRICHMENT_WORKFLOWS,
)

# Signup enrichment stays on the general and signup queues. Account audits use the Signals queue.
WORKFLOWS = [*SIGNUP_ENRICHMENT_WORKFLOWS]

ACTIVITIES = [*SIGNUP_ENRICHMENT_ACTIVITIES]

__all__ = ["WORKFLOWS", "ACTIVITIES", "ACCOUNT_AUDIT_WORKFLOWS", "ACCOUNT_AUDIT_ACTIVITIES"]
