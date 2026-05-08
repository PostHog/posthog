from products.web_analytics.backend.temporal.weekly_digest.activities import (
    get_org_id_batches,
    push_wa_digest_metrics_activity,
    run_wa_digest_batch,
    send_test_wa_digest,
)
from products.web_analytics.backend.temporal.weekly_digest.workflows import (
    WAWeeklyDigestTestWorkflow,
    WAWeeklyDigestWorkflow,
)

WORKFLOWS = [WAWeeklyDigestWorkflow, WAWeeklyDigestTestWorkflow]
ACTIVITIES = [
    get_org_id_batches,
    run_wa_digest_batch,
    push_wa_digest_metrics_activity,
    send_test_wa_digest,
]
