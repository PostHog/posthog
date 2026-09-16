from datetime import datetime

from prometheus_client import Gauge

from posthog.metrics import pushed_metrics_registry
from posthog.temporal.common.metrics import get_metric_meter

SCHEDULER_RUNS = "subscriptions_scheduler_runs"
SCHEDULER_SELECTED = "subscriptions_scheduler_selected"
SCHEDULER_OLDEST_DUE_AGE_SECONDS = "posthog_subscriptions_scheduler_oldest_due_age_seconds"
SCHEDULER_LAST_SUCCESSFUL_FETCH_TIMESTAMP_SECONDS = (
    "posthog_subscriptions_scheduler_last_successful_fetch_timestamp_seconds"
)
SCHEDULER_COHORT_TOTAL = "subscriptions_scheduler_cohort_total"
SCHEDULER_COHORT_PROCESSED = "subscriptions_scheduler_cohort_processed"
SCHEDULER_COHORT_REMAINING = "subscriptions_scheduler_cohort_remaining"
SCHEDULER_COHORT_PAGE = "subscriptions_scheduler_cohort_page"
SCHEDULER_PAGES = "subscriptions_scheduler_pages"
SCHEDULER_CHILDREN_COMPLETED = "subscriptions_scheduler_children_completed"
SCHEDULER_CHILDREN_FAILED = "subscriptions_scheduler_children_failed"
SCHEDULER_CHILDREN_ALREADY_RUNNING = "subscriptions_scheduler_children_already_running"
SCHEDULER_COHORTS_STARTED = "subscriptions_scheduler_cohorts_started"
SCHEDULER_COHORTS_COMPLETED = "subscriptions_scheduler_cohorts_completed"
SCHEDULER_LAST_COMPLETED_TIMESTAMP_SECONDS = "subscriptions_scheduler_last_completed_timestamp_seconds"


def record_scheduler_fetch(
    *,
    selected_count: int,
    oldest_due_at: datetime | None,
    now: datetime,
    has_more: bool,
    record_oldest_due_age: bool = True,
) -> None:
    meter = get_metric_meter()
    outcome = "saturated" if has_more else "empty" if selected_count == 0 else "partial"
    meter.with_additional_attributes({"outcome": outcome}).create_counter(
        SCHEDULER_RUNS,
        "Subscription scheduler fetches by whether the configured batch was exhausted.",
    ).add(1)
    meter.create_counter(
        SCHEDULER_SELECTED,
        "Due subscriptions selected for Temporal child-workflow dispatch.",
    ).add(selected_count)
    if record_oldest_due_age:
        oldest_due_age_seconds = max(0.0, (now - oldest_due_at).total_seconds()) if oldest_due_at is not None else 0.0
        with pushed_metrics_registry("temporal_subscriptions_scheduler") as registry:
            Gauge(
                SCHEDULER_OLDEST_DUE_AGE_SECONDS,
                "Age in seconds of the oldest due subscription selected by a scheduler run.",
                registry=registry,
            ).set(oldest_due_age_seconds)
            Gauge(
                SCHEDULER_LAST_SUCCESSFUL_FETCH_TIMESTAMP_SECONDS,
                "Unix timestamp of the last successful subscription scheduler fetch.",
                registry=registry,
            ).set(now.timestamp())


def record_scheduler_progress(
    *,
    total_count: int,
    processed_count: int,
    remaining_count: int,
    page_number: int,
    completed_count: int,
    already_running_count: int,
    failed_count: int,
    completed: bool,
    completed_at: datetime | None = None,
) -> None:
    """Record bounded scheduler progress without workflow- or subscription-ID labels."""
    meter = get_metric_meter()
    meter.create_gauge_float(
        SCHEDULER_COHORT_TOTAL,
        "Total subscriptions in the frozen due cohort when the scheduler started.",
    ).set(float(total_count))
    meter.create_gauge_float(
        SCHEDULER_COHORT_PROCESSED,
        "Subscriptions traversed in the current frozen due cohort.",
    ).set(float(processed_count))
    meter.create_gauge_float(
        SCHEDULER_COHORT_REMAINING,
        "Subscriptions still to traverse in the current frozen due cohort.",
    ).set(float(remaining_count))
    meter.create_gauge_float(
        SCHEDULER_COHORT_PAGE,
        "Current page number in the frozen due cohort.",
    ).set(float(page_number))
    meter.create_counter(
        SCHEDULER_PAGES,
        "Subscription scheduler pages processed.",
    ).add(1)
    meter.create_counter(
        SCHEDULER_CHILDREN_COMPLETED,
        "Subscription child workflows that completed successfully.",
    ).add(completed_count)
    meter.create_counter(
        SCHEDULER_CHILDREN_ALREADY_RUNNING,
        "Subscription child workflows skipped because that subscription was already running.",
    ).add(already_running_count)
    meter.create_counter(
        SCHEDULER_CHILDREN_FAILED,
        "Subscription child workflows that failed or were canceled.",
    ).add(failed_count)
    if page_number == 1:
        meter.create_counter(
            SCHEDULER_COHORTS_STARTED,
            "Subscription scheduler cohorts started.",
        ).add(1)
    if completed and completed_at is not None:
        meter.create_counter(
            SCHEDULER_COHORTS_COMPLETED,
            "Subscription scheduler cohorts that reached zero remaining.",
        ).add(1)
        meter.create_gauge_float(
            SCHEDULER_LAST_COMPLETED_TIMESTAMP_SECONDS,
            "Unix timestamp when a subscription scheduler cohort last reached zero remaining.",
        ).set(completed_at.timestamp())
