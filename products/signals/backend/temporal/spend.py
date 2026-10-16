from dataclasses import replace
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.common.utils import asyncify

    from products.signals.backend.spend import (
        SignalMetadataChange,
        SignalSpendPublication,
        SignalSpendUpdate,
        settle_signal_task_spend,
    )
    from products.signals.backend.spend_metadata import confirm_signal_spend_metadata, publish_signal_spend_metadata


@activity.defn
@asyncify
def update_signal_spend_activity(input: SignalSpendUpdate) -> SignalSpendPublication:
    settle_signal_task_spend(team_id=input.team_id, signal_id=input.signal_id)
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
        self._changes: list[SignalMetadataChange] = []

    @workflow.signal
    def refresh(self) -> None:
        self._updates += 1

    @workflow.signal
    def update_metadata(self, change: SignalMetadataChange) -> None:
        self._changes.append(change)
        self._updates += 1

    @workflow.run
    async def run(self, input: SignalSpendUpdate) -> None:
        self._changes = input.changes + self._changes
        while True:
            # Separate replacements into Kafka timestamp seconds, and coalesce queued notifications.
            await workflow.sleep(1)
            updates = self._updates
            changes, self._changes = self._changes, []
            publication = await workflow.execute_activity(
                update_signal_spend_activity,
                replace(input, changes=changes),
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
                workflow.continue_as_new(replace(input, changes=self._changes))
