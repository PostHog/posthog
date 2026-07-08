from temporalio import activity

from posthog.temporal.common.utils import asyncify


@activity.defn
@asyncify
def run_loop_trigger_activity(loop_trigger_id: str) -> None:
    from ...logic.services.loop_runs import fire_loop, render_trigger_context
    from ...models import LoopTrigger

    trigger = LoopTrigger.objects.unscoped().select_related("loop").get(id=loop_trigger_id)
    loop = trigger.loop
    trigger_context = render_trigger_context(trigger.type, {"trigger_id": str(trigger.id)}, loop)
    fire_loop(loop, trigger, fire_key=activity.info().workflow_id, trigger_context=trigger_context)
