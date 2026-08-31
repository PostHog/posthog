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
from products.subscriptions.backend.temporal.pulse import PulseWorkflow

WORKFLOWS = [PulseWorkflow]
ACTIVITIES = [
    prepare_pulse_workflow,
    await_existing_pulse_workflow_result,
    prepare_pulse_delivery_bundle,
    record_pulse_delivery_bundle_preparation_failure,
    advance_pulse_workflow,
    finalize_timed_out_pulse_workflow,
    cancel_pulse_workflow,
    record_pulse_parent_failure,
]
