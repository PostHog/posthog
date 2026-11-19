"""Facade for warehouse destinations.

Other products import only this package. The functions here hand out contracts,
never the classes that implement a destination.
"""

from ..logic import registry
from .contracts import Destination, DestinationConnection, DestinationFactory, DestinationLogger


def register_destination(destination_type: str, factory: DestinationFactory, *, replace: bool = False) -> None:
    """Register a factory for a destination type.

    Raises `ValueError` when the type already has a factory, unless `replace` is True.
    """
    registry.register(destination_type, factory, replace=replace)


def get_destination(connection: DestinationConnection, *, logger: DestinationLogger | None = None) -> Destination:
    """Build the destination for `connection.destination_type`.

    Raises `UnsupportedDestinationError` when no factory exists for the type.
    """
    factory = registry.resolve(connection.destination_type)
    return factory(connection, logger=logger)


def supported_destination_types() -> tuple[str, ...]:
    return registry.registered_types()
