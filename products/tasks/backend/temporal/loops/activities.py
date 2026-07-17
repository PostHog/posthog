from temporalio import activity

from posthog.temporal.common.utils import asyncify


@activity.defn
@asyncify
def run_loop_trigger_activity(loop_trigger_id: str) -> None:
    from ...logic.services.loop_runs import fire_loop, render_trigger_context
    from ...models import LoopTrigger

    fire_key = activity.info().workflow_id
    assert fire_key is not None
    # A scheduled occurrence can land after its trigger row was deleted (trigger re-sync or
    # loop deletion tears the Schedule down best-effort); that's a no-op, not a retryable error.
    trigger = LoopTrigger.objects.unscoped().select_related("loop").filter(id=loop_trigger_id).first()
    if trigger is None:
        activity.logger.info(f"Loop trigger {loop_trigger_id} no longer exists, skipping fire")
        return
    loop = trigger.loop
    trigger_context = render_trigger_context(trigger.type, {"trigger_id": str(trigger.id)}, loop)
    fire_loop(loop, trigger, fire_key=fire_key, trigger_context=trigger_context)
