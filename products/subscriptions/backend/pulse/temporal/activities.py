import temporalio.activity

from products.subscriptions.backend.pulse.temporal.inputs import (
    PulseDeliveryBundleInput,
    PulseDeliveryBundleRef,
    PulseStartInput,
    PulseWorkflowInput,
    PulseWorkflowResult,
)


@temporalio.activity.defn
def prepare_pulse_workflow(input: PulseStartInput) -> PulseWorkflowInput | None:
    from products.subscriptions.backend.facade import pulse as pulse_facade  # noqa: PLC0415, I001 — facade is wired after the Temporal package loads

    return pulse_facade.prepare_pulse_workflow(input)


@temporalio.activity.defn
def advance_pulse_workflow(input: PulseWorkflowInput) -> PulseWorkflowResult | None:
    from products.subscriptions.backend.facade import pulse as pulse_facade  # noqa: PLC0415, I001 — facade is wired after the Temporal package loads

    return pulse_facade.advance_pulse_workflow(input)


@temporalio.activity.defn
def finalize_timed_out_pulse_workflow(input: PulseWorkflowInput) -> PulseWorkflowResult:
    from products.subscriptions.backend.facade import pulse as pulse_facade  # noqa: PLC0415, I001 — facade is wired after the Temporal package loads

    return pulse_facade.finalize_timed_out_pulse_workflow(input)


@temporalio.activity.defn
def cancel_pulse_workflow(input: PulseWorkflowInput) -> PulseWorkflowResult:
    from products.subscriptions.backend.facade import pulse as pulse_facade  # noqa: PLC0415, I001 — facade is wired after the Temporal package loads

    return pulse_facade.cancel_pulse_workflow(input)


@temporalio.activity.defn
def record_pulse_parent_failure(input: PulseStartInput, failure_code: str) -> None:
    from products.subscriptions.backend.facade import pulse as pulse_facade  # noqa: PLC0415, I001 — facade is wired after the Temporal package loads

    pulse_facade.record_pulse_parent_failure(input, failure_code)


@temporalio.activity.defn
def await_existing_pulse_workflow_result(input: PulseStartInput) -> PulseWorkflowResult | None:
    from products.subscriptions.backend.facade import pulse as pulse_facade  # noqa: PLC0415, I001 — facade is wired after the Temporal package loads

    return pulse_facade.await_existing_pulse_workflow_result(input)


@temporalio.activity.defn
def prepare_pulse_delivery_bundle(input: PulseDeliveryBundleInput) -> PulseDeliveryBundleRef:
    from products.subscriptions.backend.facade import pulse as pulse_facade  # noqa: PLC0415, I001 — facade is wired after the Temporal package loads

    return pulse_facade.prepare_pulse_delivery_bundle(input)


@temporalio.activity.defn
def record_pulse_delivery_bundle_preparation_failure(input: PulseDeliveryBundleInput) -> PulseDeliveryBundleRef:
    from products.subscriptions.backend.facade import pulse as pulse_facade  # noqa: PLC0415, I001 — facade is wired after the Temporal package loads

    return pulse_facade.record_pulse_delivery_bundle_preparation_failure(input)
