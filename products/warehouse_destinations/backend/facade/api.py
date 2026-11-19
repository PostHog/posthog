"""Facade for warehouse destinations.

Other products import only this package. The functions here hand out contracts, never the
classes that implement a destination. Tests replace a destination with
`facade.testing.override_destination`.
"""

from ..logic import registry
from .contracts import Destination, DestinationCapabilities, DestinationConnection, DestinationLogger
from .enums import DestinationType


def get_destination(connection: DestinationConnection, *, logger: DestinationLogger | None = None) -> Destination:
    """Build the destination for `connection.destination_type`. Does not connect.

    Raises `UnsupportedDestinationError` when no destination exists for the type.
    """
    factory = registry.resolve(connection.destination_type)
    return factory(connection, logger=logger)


def get_capabilities(destination_type: DestinationType) -> DestinationCapabilities:
    """Return what `destination_type` supports, without a connection and without vendor SDKs.

    Raises `UnsupportedDestinationError` when no destination exists for the type.
    """
    return registry.capabilities_for(DestinationType(destination_type))


def supported_destination_types() -> tuple[DestinationType, ...]:
    """The destination types `get_destination` can build, sorted."""
    return registry.registered_types()
