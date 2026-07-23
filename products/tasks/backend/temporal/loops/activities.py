import logging

from temporalio import activity

from posthog.temporal.common.utils import asyncify

logger = logging.getLogger(__name__)


@activity.defn
@asyncify
def run_loop_trigger_activity(loop_trigger_id: str) -> None:
    fire_key = activity.info().workflow_id
    assert fire_key is not None
    run_loop_trigger(loop_trigger_id, fire_key)


def run_loop_trigger(loop_trigger_id: str, fire_key: str) -> None:
    """Fire a loop trigger, then finalize it if it was one-time. Plain function (no activity
    context) so the fire-and-cleanup behavior is unit-testable directly."""
    from ...logic.services.loop_runs import fire_loop, render_trigger_context
    from ...loop_service import complete_one_time_trigger
    from ...models import LoopTrigger

    # A scheduled occurrence can land after its trigger row was deleted (trigger re-sync or
    # loop deletion tears the Schedule down best-effort); that's a no-op, not a retryable error.
    trigger = LoopTrigger.objects.unscoped().select_related("loop").filter(id=loop_trigger_id).first()
    if trigger is None:
        logger.info("Loop trigger %s no longer exists, skipping fire", loop_trigger_id)
        return

    loop = trigger.loop
    trigger_context = render_trigger_context(trigger.type, {"trigger_id": str(trigger.id)}, loop)
    fire_loop(loop, trigger, fire_key=fire_key, trigger_context=trigger_context)

    # A one-time (`run_at`) trigger's Schedule is spent the instant it fires (remaining_actions
    # reaches 0) and Temporal never GCs it, so tear it down and mark the trigger completed. Runs
    # regardless of the fire outcome (rate-capped, disabled, ...): the single occurrence is used up
    # either way. Best-effort, the fire already happened and must not be undone by a cleanup hiccup.
    if (trigger.config or {}).get("run_at"):
        try:
            complete_one_time_trigger(trigger)
        except Exception:
            logger.exception("Failed to complete one-time loop trigger %s", loop_trigger_id)
