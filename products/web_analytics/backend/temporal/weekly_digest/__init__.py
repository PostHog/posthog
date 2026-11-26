from typing import TYPE_CHECKING

from products.web_analytics.backend.temporal.weekly_digest.activities import (
    get_org_batch_page,
    push_wa_digest_metrics_activity,
    run_wa_digest_batch,
    send_test_wa_digest,
)
from products.web_analytics.backend.temporal.weekly_digest.workflows import (
    WAWeeklyDigestTestWorkflow,
    WAWeeklyDigestWorkflow,
)

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [WAWeeklyDigestWorkflow, WAWeeklyDigestTestWorkflow]
ACTIVITIES: list[ActivityDefinition] = [
    get_org_batch_page,
    run_wa_digest_batch,
    push_wa_digest_metrics_activity,
    send_test_wa_digest,
]
