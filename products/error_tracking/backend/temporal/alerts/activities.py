import posthoganalytics
from temporalio import activity

from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.temporal.alerts.delivery import deliver_alert_notifications
from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs
from products.error_tracking.backend.temporal.alerts.workflow import ACTIVITY_RETRY_POLICY


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def deliver_alert_notifications_activity(inputs: AlertDeliveryWorkflowInputs) -> int:
    final_attempt = activity.info().attempt >= ACTIVITY_RETRY_POLICY.maximum_attempts
    return deliver_alert_notifications(inputs, final_attempt=final_attempt)


ACTIVITIES = [deliver_alert_notifications_activity]
