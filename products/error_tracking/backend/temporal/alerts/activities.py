import posthoganalytics
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.temporal.alerts.delivery import AlertThreadBusyError, deliver_alert_notifications
from products.error_tracking.backend.temporal.alerts.types import THREAD_BUSY_ERROR_TYPE, AlertDeliveryWorkflowInputs


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def deliver_alert_notifications_activity(inputs: AlertDeliveryWorkflowInputs) -> int:
    try:
        return deliver_alert_notifications(inputs)
    except AlertThreadBusyError as error:
        # Non-retryable here so contention never spends the activity's failure budget;
        # the workflow waits and schedules the activity again.
        raise ApplicationError(str(error), type=THREAD_BUSY_ERROR_TYPE, non_retryable=True) from error


ACTIVITIES = [deliver_alert_notifications_activity]
