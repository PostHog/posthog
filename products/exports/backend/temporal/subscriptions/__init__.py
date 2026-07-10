from products.exports.backend.temporal.subscriptions.activities import (
    advance_next_delivery_date,
    create_delivery_record,
    create_export_assets,
    deliver_subscription,
    fetch_due_subscriptions_activity,
    update_delivery_record,
    validate_subscription_for_delivery,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.activities import generate_ai_subscription_report
from products.exports.backend.temporal.subscriptions.pulse_subscription.activities import (
    cleanup_skipped_pulse_brief,
    prepare_pulse_brief_subscription,
    render_pulse_brief_for_delivery,
)
from products.exports.backend.temporal.subscriptions.snapshot_activities import snapshot_subscription_insights
from products.exports.backend.temporal.subscriptions.workflows import (
    HandleSubscriptionValueChangeWorkflow,
    ProcessAISubscriptionWorkflow,
    ProcessPulseSubscriptionWorkflow,
    ProcessSubscriptionWorkflow,
    ScheduleAllSubscriptionsWorkflow,
)

WORKFLOWS = [
    ScheduleAllSubscriptionsWorkflow,
    HandleSubscriptionValueChangeWorkflow,
    ProcessSubscriptionWorkflow,
    ProcessAISubscriptionWorkflow,
    ProcessPulseSubscriptionWorkflow,
]

ACTIVITIES = [
    fetch_due_subscriptions_activity,
    validate_subscription_for_delivery,
    create_export_assets,
    deliver_subscription,
    generate_ai_subscription_report,
    prepare_pulse_brief_subscription,
    cleanup_skipped_pulse_brief,
    render_pulse_brief_for_delivery,
    advance_next_delivery_date,
    create_delivery_record,
    update_delivery_record,
    snapshot_subscription_insights,
]
