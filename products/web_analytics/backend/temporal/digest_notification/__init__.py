from typing import TYPE_CHECKING

from products.web_analytics.backend.temporal.digest_notification.activities import (
    get_org_batch_page,
    run_wa_digest_notification_batch,
    send_test_wa_digest_notification,
)
from products.web_analytics.backend.temporal.digest_notification.workflows import (
    WADigestNotificationTestWorkflow,
    WADigestNotificationWorkflow,
)

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [WADigestNotificationWorkflow, WADigestNotificationTestWorkflow]
ACTIVITIES: list[ActivityDefinition] = [
    get_org_batch_page,
    run_wa_digest_notification_batch,
    send_test_wa_digest_notification,
]
