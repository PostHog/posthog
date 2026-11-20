"""Checks every destination runs against its capabilities before it touches anything."""

from products.warehouse_destinations.backend.facade.contracts import (
    DestinationCapabilities,
    DestinationConfigurationError,
    TargetRef,
)


def check_ref(capabilities: DestinationCapabilities, ref: TargetRef) -> None:
    """Raise a CONFIGURATION-kind error when the destination cannot serve `ref`."""
    if ref.write_mode not in capabilities.write_modes:
        message = f"This destination does not support {ref.write_mode} writes"
        raise DestinationConfigurationError(message, detail=message)

    if len(ref.namespace) != capabilities.namespace_depth:
        message = (
            f"The namespace must have {capabilities.namespace_depth} part(s), "
            f"got {len(ref.namespace)}: {list(ref.namespace)}"
        )
        raise DestinationConfigurationError(message, detail=message)


def check_batch_key(capabilities: DestinationCapabilities, ref: TargetRef, batch_key: str | None) -> None:
    """Raise a CONFIGURATION-kind error when a `batch_key` comes with a mode that cannot honor it."""
    if batch_key is not None and ref.write_mode not in capabilities.batch_key_modes:
        message = f"This destination cannot honor a batch key for {ref.write_mode} writes"
        raise DestinationConfigurationError(message, detail=message)
