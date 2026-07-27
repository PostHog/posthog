from products.web_analytics.backend.temporal.digest_notification.activities import (
    get_org_batch_page,
    run_wa_digest_notification_batch,
    send_test_wa_digest_notification,
)
from products.web_analytics.backend.temporal.digest_notification.workflows import (
    WADigestNotificationTestWorkflow,
    WADigestNotificationWorkflow,
)

WORKFLOWS = [WADigestNotificationWorkflow, WADigestNotificationTestWorkflow]
ACTIVITIES = [
    get_org_batch_page,
    run_wa_digest_notification_batch,
    send_test_wa_digest_notification,
]
