from products.exports.backend.temporal.subscriptions.activities import (
    advance_next_delivery_date,
    advance_next_delivery_date_v2,
    advance_subscription_scheduler_cursor_activity,
    complete_subscription_scheduler_claim_activity,
    confirm_subscription_scheduler_claim_activity,
    create_delivery_record,
    create_export_assets,
    deliver_subscription,
    deliver_subscription_v2,
    fetch_claimed_due_subscriptions_activity,
    fetch_due_subscriptions_activity,
    notify_subscription_delivery_failure,
    recover_subscription_scheduler_claims_activity,
    release_subscription_scheduler_claim_activity,
    update_delivery_record,
    validate_subscription_for_delivery,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.activities import generate_ai_subscription_report
from products.exports.backend.temporal.subscriptions.snapshot_activities import snapshot_subscription_insights
from products.exports.backend.temporal.subscriptions.workflows import (
    HandleSubscriptionValueChangeWorkflow,
    ProcessAISubscriptionWorkflow,
    ProcessSubscriptionWorkflow,
    ScheduleAllSubscriptionsWorkflow,
)

WORKFLOWS = [
    ScheduleAllSubscriptionsWorkflow,
    HandleSubscriptionValueChangeWorkflow,
    ProcessSubscriptionWorkflow,
    ProcessAISubscriptionWorkflow,
]

ACTIVITIES = [
    fetch_due_subscriptions_activity,
    fetch_claimed_due_subscriptions_activity,
    advance_subscription_scheduler_cursor_activity,
    recover_subscription_scheduler_claims_activity,
    confirm_subscription_scheduler_claim_activity,
    complete_subscription_scheduler_claim_activity,
    release_subscription_scheduler_claim_activity,
    validate_subscription_for_delivery,
    create_export_assets,
    deliver_subscription,
    deliver_subscription_v2,
    notify_subscription_delivery_failure,
    generate_ai_subscription_report,
    advance_next_delivery_date,
    advance_next_delivery_date_v2,
    create_delivery_record,
    update_delivery_record,
    snapshot_subscription_insights,
]
