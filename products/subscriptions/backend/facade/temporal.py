"""Public Temporal wiring for subscription-owned proactive Pulse.

Keep Temporal imports out of ``facade.api`` so light subscription consumers do
not load Temporal. Core and other products register or invoke these exact
objects through this module rather than reaching into Pulse internals.
"""

from products.subscriptions.backend.pulse.dispatch_snapshot import (
    build_scheduled_proactive_dispatch_manifest,
    build_scheduled_proactive_dispatch_snapshot,
    build_scheduled_proactive_dispatch_snapshots,
    resolve_scheduled_proactive_dispatch_manifest,
)
from products.subscriptions.backend.pulse.temporal.activities import (
    advance_pulse_workflow,
    await_existing_pulse_workflow_result,
    cancel_pulse_workflow,
    finalize_timed_out_pulse_workflow,
    prepare_pulse_delivery_bundle,
    prepare_pulse_workflow,
    record_pulse_delivery_bundle_preparation_failure,
    record_pulse_parent_failure,
)
from products.subscriptions.backend.pulse.temporal.registry import ACTIVITIES, WORKFLOWS
from products.subscriptions.backend.temporal.pulse import PulseWorkflow as _PulseWorkflow

from .contracts import (
    ProactiveDispatchSnapshot,
    PulseDeliveryBundleInput,
    PulseDeliveryBundleRef,
    PulseStartInput,
    PulseWorkflowInput,
    PulseWorkflowResult,
    ScheduledPulseEligibilityInput,
)

PULSE_WORKFLOW_RUN = _PulseWorkflow.run

__all__ = [
    "ACTIVITIES",
    "PULSE_WORKFLOW_RUN",
    "WORKFLOWS",
    "ProactiveDispatchSnapshot",
    "PulseDeliveryBundleInput",
    "PulseDeliveryBundleRef",
    "PulseStartInput",
    "PulseWorkflowInput",
    "PulseWorkflowResult",
    "ScheduledPulseEligibilityInput",
    "advance_pulse_workflow",
    "await_existing_pulse_workflow_result",
    "build_scheduled_proactive_dispatch_manifest",
    "build_scheduled_proactive_dispatch_snapshot",
    "build_scheduled_proactive_dispatch_snapshots",
    "cancel_pulse_workflow",
    "finalize_timed_out_pulse_workflow",
    "prepare_pulse_delivery_bundle",
    "prepare_pulse_workflow",
    "record_pulse_delivery_bundle_preparation_failure",
    "record_pulse_parent_failure",
    "resolve_scheduled_proactive_dispatch_manifest",
]
