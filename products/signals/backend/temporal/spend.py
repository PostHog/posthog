from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.common.utils import asyncify

    from products.signals.backend.spend import SignalSpendPublication, SignalSpendUpdate
    from products.signals.backend.spend_metadata import confirm_signal_spend_metadata, publish_signal_spend_metadata


@activity.defn
@asyncify
def update_signal_spend_activity(input: SignalSpendUpdate) -> SignalSpendPublication:
    return publish_signal_spend_metadata(input)


@activity.defn
@asyncify
def confirm_signal_spend_activity(input: SignalSpendPublication) -> None:
    if not confirm_signal_spend_metadata(input):
        raise ApplicationError("Signal spend metadata is not yet visible in ClickHouse", type="SignalSpendNotVisible")


@workflow.defn(name="update-signal-spend")
class UpdateSignalSpendWorkflow(PostHogWorkflow):
    inputs_cls = SignalSpendUpdate

    def __init__(self) -> None:
        self._updates = 0

    @workflow.signal
    def refresh(self) -> None:
        self._updates += 1

    @workflow.run
    async def run(self, input: SignalSpendUpdate) -> None:
        while True:
            # Separate replacements into Kafka timestamp seconds, and coalesce queued notifications.
            await workflow.sleep(1)
            updates = self._updates
            publication = await workflow.execute_activity(
                update_signal_spend_activity,
                input,
                start_to_close_timeout=timedelta(minutes=1),
                schedule_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), maximum_interval=timedelta(seconds=10)),
            )
            await workflow.execute_activity(
                confirm_signal_spend_activity,
                publication,
                start_to_close_timeout=timedelta(minutes=1),
                schedule_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), maximum_interval=timedelta(seconds=10)),
            )
            if updates == self._updates:
                return
            if workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(input)
