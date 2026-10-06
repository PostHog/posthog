"""Errors a destination delivery raises.

Kept apart from `delivery` so a writer can raise them without importing the delivery path, and
so the load consumer can match on the marker without importing any writer.
"""

from __future__ import annotations

# The load consumer matches this substring to fail a run on its first attempt. Changing it
# silently turns every configuration error back into a retried, reported failure.
DESTINATION_CONFIGURATION_ERROR_MARKER = "Destination configuration error"

MISSING_INTEGRATION_DETAIL = (
    "The destination's connection details no longer exist. Connect the destination again, then run the sync again."
)


class DestinationDeliveryError(Exception):
    """One destination could not take the batch, so the batch is not done.

    Carries the destination's name so a single job's `latest_error` still says which
    destination stopped the sync.
    """

    def __init__(self, destination_name: str, cause: Exception | str) -> None:
        self.destination_name = destination_name
        self.cause = cause
        super().__init__(f"{destination_name}: {cause}")


class DestinationConfigurationError(DestinationDeliveryError):
    """The destination's own settings stop every connection, so no retry can succeed.

    Raised before anything is staged, which lets the run fail on its first attempt and lets
    the abort path skip a destination it could not connect to anyway.
    """

    def __init__(self, destination_name: str, detail: str) -> None:
        self.detail = detail
        super().__init__(destination_name, f"{DESTINATION_CONFIGURATION_ERROR_MARKER}. {detail}")


def is_configuration_failure_of(reason: str, destination_name: str) -> bool:
    """Whether a run's failure `reason` is a configuration error raised by this destination.

    The prefix must start the reason or follow a `: ` separator, so a destination named `Prod`
    does not match a failure of one named `My Prod`.
    """
    prefix = f"{destination_name}: {DESTINATION_CONFIGURATION_ERROR_MARKER}"
    return reason.startswith(prefix) or f": {prefix}" in reason
