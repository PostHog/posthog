from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.exceptions import SandboxNotFoundError
from products.tasks.backend.logic.services.sandbox import get_sandbox_class_for_sandbox_id


@frozen
class GetSandboxExitReasonInput:
    sandbox_id: str


@activity.defn
@asyncify
def get_sandbox_exit_reason(input: GetSandboxExitReasonInput) -> str | None:
    try:
        sandbox = get_sandbox_class_for_sandbox_id(input.sandbox_id).get_by_id(input.sandbox_id)
    except SandboxNotFoundError:
        return None
    return sandbox.exit_reason()
