"""Registry that maps a destination type to the factory that builds it."""

import importlib

from ..facade.contracts import DestinationFactory, UnsupportedDestinationError

# Destination type -> "module.path:Attribute". `resolve` imports the module on first
# use, so vendor SDKs load only when a caller asks for that destination.
_BUILTIN_FACTORIES: dict[str, str] = {
    "Postgres": "products.warehouse_destinations.backend.destinations.postgres.destination:PostgresDestination",
}

_registry: dict[str, DestinationFactory] = {}


def register(destination_type: str, factory: DestinationFactory, *, replace: bool = False) -> None:
    """Register `factory` for `destination_type`.

    Raises `ValueError` when the type already has a factory, built in or registered,
    unless `replace` is True.
    """
    if not replace and (destination_type in _registry or destination_type in _BUILTIN_FACTORIES):
        raise ValueError(f"A factory is already registered for destination type '{destination_type}'")

    _registry[destination_type] = factory


def resolve(destination_type: str) -> DestinationFactory:
    """Return the factory for `destination_type`.

    Raises `UnsupportedDestinationError` when no factory exists for the type.
    """
    try:
        return _registry[destination_type]
    except KeyError:
        pass

    try:
        import_path = _BUILTIN_FACTORIES[destination_type]
    except KeyError:
        raise UnsupportedDestinationError(f"Unsupported destination type: '{destination_type}'") from None

    return _import_factory(import_path)


def registered_types() -> tuple[str, ...]:
    return tuple(sorted(_registry.keys() | _BUILTIN_FACTORIES.keys()))


def _import_factory(import_path: str) -> DestinationFactory:
    module_path, separator, attribute = import_path.partition(":")
    if not separator or not module_path or not attribute:
        raise ValueError(f"Factory path must look like 'module.path:Attribute', got '{import_path}'")

    module = importlib.import_module(module_path)
    factory = getattr(module, attribute)
    if not callable(factory):
        raise TypeError(f"Factory '{import_path}' is not callable")
    return factory
