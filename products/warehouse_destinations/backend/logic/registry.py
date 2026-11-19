"""Registry that maps a destination type to the factory that builds it, its spec and its config.

Built-in destinations are listed by import path, so a vendor SDK loads only when a caller asks
for that destination. The capabilities and the spec of each built-in sit in modules without
vendor imports, so reading them loads no SDK. The generated config class of a type is found by
the naming rule of `config_generator`, so it needs no entry here.
"""

import typing
import importlib
import contextlib
from collections.abc import Iterator

from posthog.dataclasses import frozen

from ..facade.configs.base import DestinationConfig
from ..facade.contracts import DestinationCapabilities, DestinationFactory, UnsupportedDestinationError
from ..facade.destination_spec import DestinationSpec
from ..facade.enums import DestinationType
from .config_generator import CONFIGS_PACKAGE, config_class_name, config_module_name


@frozen
class _Builtin:
    factory: str
    capabilities: str
    spec: str


_POSTGRES_PACKAGE = "products.warehouse_destinations.backend.destinations.postgres"

_BUILTINS: dict[DestinationType, _Builtin] = {
    DestinationType.POSTGRES: _Builtin(
        factory=f"{_POSTGRES_PACKAGE}.destination:PostgresDestination",
        capabilities=f"{_POSTGRES_PACKAGE}.capabilities:POSTGRES_CAPABILITIES",
        spec=f"{_POSTGRES_PACKAGE}.spec:POSTGRES_SPEC",
    ),
}

_overrides: dict[DestinationType, DestinationFactory] = {}


def resolve(destination_type: DestinationType) -> DestinationFactory:
    """Return the factory for `destination_type`.

    Raises `UnsupportedDestinationError` when no factory exists for the type.
    """
    if destination_type in _overrides:
        return _overrides[destination_type]
    import_path = _builtin(destination_type).factory
    factory = _import_attribute(import_path)
    if not callable(factory):
        raise TypeError(f"Factory '{import_path}' is not callable")
    return typing.cast(DestinationFactory, factory)


def capabilities_for(destination_type: DestinationType) -> DestinationCapabilities:
    """Return the capabilities of `destination_type` without building a destination.

    Raises `UnsupportedDestinationError` when no factory exists for the type.
    """
    if destination_type in _overrides:
        return _overrides[destination_type].capabilities

    capabilities = _import_attribute(_builtin(destination_type).capabilities)
    if not isinstance(capabilities, DestinationCapabilities):
        raise TypeError(f"Capabilities of '{destination_type}' are not DestinationCapabilities")
    return capabilities


def spec_for(destination_type: DestinationType) -> DestinationSpec:
    """Return the spec of a built-in destination. Overrides have no spec.

    Raises `UnsupportedDestinationError` when no built-in exists for the type.
    """
    import_path = _builtin(destination_type).spec
    spec = _import_attribute(import_path)
    if not isinstance(spec, DestinationSpec) or spec.destinationType != destination_type:
        raise TypeError(f"Spec '{import_path}' is not the DestinationSpec of '{destination_type}'")
    return spec


def spec_import_path(destination_type: DestinationType) -> str:
    return _builtin(destination_type).spec


def config_class_for(destination_type: DestinationType) -> type[DestinationConfig]:
    """Return the generated config class of a built-in destination.

    Raises `UnsupportedDestinationError` when no built-in exists for the type.
    """
    _builtin(destination_type)
    module = importlib.import_module(f"{CONFIGS_PACKAGE}.{config_module_name(destination_type)}")
    config_class = getattr(module, config_class_name(destination_type))
    if not (isinstance(config_class, type) and issubclass(config_class, DestinationConfig)):
        raise TypeError(f"Config of '{destination_type}' is not a DestinationConfig")
    return config_class


def builtin_types() -> tuple[DestinationType, ...]:
    """The destination types with a built-in destination, sorted. Overrides are not included."""
    return tuple(sorted(_BUILTINS))


def registered_types() -> tuple[DestinationType, ...]:
    return tuple(sorted(_overrides.keys() | _BUILTINS.keys()))


@contextlib.contextmanager
def override(destination_type: DestinationType, factory: DestinationFactory) -> Iterator[None]:
    """Use `factory` for `destination_type` inside the context, then restore the previous one."""
    previous = _overrides.get(destination_type)
    _overrides[destination_type] = factory
    try:
        yield
    finally:
        if previous is None:
            _overrides.pop(destination_type, None)
        else:
            _overrides[destination_type] = previous


def _builtin(destination_type: DestinationType) -> _Builtin:
    try:
        return _BUILTINS[destination_type]
    except KeyError:
        raise UnsupportedDestinationError(
            f"Unsupported destination type: '{destination_type}'",
            detail=f"PostHog cannot write to {destination_type} destinations yet.",
        ) from None


def _import_attribute(import_path: str) -> object:
    module_path, separator, attribute = import_path.partition(":")
    if not separator or not module_path or not attribute:
        raise ValueError(f"Import path must look like 'module.path:Attribute', got '{import_path}'")

    module = importlib.import_module(module_path)
    return getattr(module, attribute)
