from uuid import UUID

from temporalio import activity

from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.utils import asyncify

from products.messaging.backend.provider_imports.runs import finish_run, run_step
from products.messaging.backend.temporal.inputs import ProviderImportRunInputs, ProviderImportStepInputs


@activity.defn(name="messaging-provider-import.run_step")
@asyncify
def run_provider_import_step_activity(inputs: ProviderImportStepInputs) -> None:
    with HeartbeaterSync():
        run_step(inputs.team_id, UUID(inputs.run_id), inputs.step, activity.info().attempt)


@activity.defn(name="messaging-provider-import.finish_run")
@asyncify
def finish_provider_import_run_activity(inputs: ProviderImportRunInputs) -> None:
    finish_run(inputs.team_id, UUID(inputs.run_id))
