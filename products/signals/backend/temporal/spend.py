from dataclasses import replace
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.common.utils import asyncify

    from products.signals.backend.spend import SignalMetadataChange, SignalSpendPublication, SignalSpendUpdate
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
        self._published_updates = 0
        self._publication_failed = False
        self._changes: list[SignalMetadataChange] = []

    @workflow.signal
    def refresh(self) -> None:
        self._updates += 1

    @workflow.signal
    def update_metadata(self, change: SignalMetadataChange) -> None:
        self._changes.append(change)
        self._updates += 1

    @workflow.update
    async def publish_spend(self) -> None:
        self._updates += 1
        requested = self._updates
        await workflow.wait_condition(lambda: self._published_updates >= requested or self._publication_failed)
        if self._published_updates < requested:
            raise ApplicationError("Signal spend metadata publication failed")

    @workflow.run
    async def run(self, input: SignalSpendUpdate) -> None:
        self._changes = input.changes + self._changes
        while True:
            # Separate replacements into Kafka timestamp seconds, and coalesce queued notifications.
            await workflow.sleep(1)
            updates = self._updates
            changes, self._changes = self._changes, []
            try:
                publication = await workflow.execute_activity(
                    update_signal_spend_activity,
                    replace(input, changes=changes),
                    start_to_close_timeout=timedelta(minutes=1),
                    schedule_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=1), maximum_interval=timedelta(seconds=10)
                    ),
                )
                self._published_updates = updates
                await workflow.execute_activity(
                    confirm_signal_spend_activity,
                    publication,
                    start_to_close_timeout=timedelta(minutes=1),
                    schedule_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=1), maximum_interval=timedelta(seconds=10)
                    ),
                )
            except ActivityError:
                self._publication_failed = True
                await workflow.wait_condition(workflow.all_handlers_finished)
                raise
            if updates == self._updates:
                await workflow.wait_condition(
                    lambda: self._published_updates != self._updates or workflow.all_handlers_finished()
                )
                if updates == self._updates:
                    return
            if workflow.info().is_continue_as_new_suggested() and workflow.all_handlers_finished():
                workflow.continue_as_new(replace(input, changes=self._changes))
