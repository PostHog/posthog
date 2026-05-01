from products.web_analytics.backend.temporal.weekly_digest.activities import (
    build_and_send_wa_digest_for_org,
    get_orgs_for_wa_digest,
    send_test_wa_digest,
)
from products.web_analytics.backend.temporal.weekly_digest.workflows import (
    WAWeeklyDigestTestWorkflow,
    WAWeeklyDigestWorkflow,
)

WORKFLOWS = [WAWeeklyDigestWorkflow, WAWeeklyDigestTestWorkflow]
ACTIVITIES = [get_orgs_for_wa_digest, build_and_send_wa_digest_for_org, send_test_wa_digest]
