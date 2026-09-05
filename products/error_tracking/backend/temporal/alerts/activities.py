import posthoganalytics
from temporalio import activity

from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.temporal.alerts.delivery import deliver_alert_notifications
from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def deliver_alert_notifications_activity(inputs: AlertDeliveryWorkflowInputs) -> int:
    return deliver_alert_notifications(inputs)


ACTIVITIES = [deliver_alert_notifications_activity]
