from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.common.utils import asyncify

    from products.signals.backend.spend import SignalSpendUpdate
    from products.signals.backend.spend_metadata import refresh_signal_spend_metadata


@activity.defn
@asyncify
def update_signal_spend_activity(input: SignalSpendUpdate) -> None:
    if not refresh_signal_spend_metadata(team_id=input.team_id, signal_id=input.signal_id):
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
            updates = self._updates
            await workflow.execute_activity(
                update_signal_spend_activity,
                input,
                start_to_close_timeout=timedelta(minutes=1),
                schedule_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(milliseconds=100), maximum_interval=timedelta(seconds=10)
                ),
            )
            if updates == self._updates:
                return
            if workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(input)
