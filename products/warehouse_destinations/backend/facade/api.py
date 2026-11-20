"""Facade for warehouse destinations.

Other products import only this package. The functions here hand out contracts, never the
classes that implement a destination. Tests replace a destination with
`facade.testing.override_destination`.

A caller with stored settings turns them into a typed config, then builds the destination:

    config = parse_destination_config(DestinationType.POSTGRES, stored_settings)
    destination = get_destination(DestinationConnection(team_id=team_id, config=config))

`get_destination_spec` describes the settings of a type, for example to render a form.
"""

from collections.abc import Mapping
from typing import Any

from typed_config import ConfigValueError, UndecryptedConfigError

from ..logic import registry
from .configs.base import DestinationConfig
from .contracts import (
    Destination,
    DestinationCapabilities,
    DestinationConfigurationError,
    DestinationConnection,
    DestinationLogger,
    UnsupportedDestinationError,
)
from .destination_spec import DestinationSpec
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


def get_destination_spec(destination_type: DestinationType) -> DestinationSpec:
    """Return the settings form of `destination_type`, without vendor SDKs.

    Raises `UnsupportedDestinationError` when no built-in destination exists for the type.
    """
    return registry.spec_for(_destination_type(destination_type))


def parse_destination_config(destination_type: DestinationType, data: Mapping[str, Any]) -> DestinationConfig:
    """Parse stored settings into the generated config class of `destination_type`.

    Raises a CONFIGURATION-kind `DestinationConfigurationError` when a value is missing, has
    the wrong type or is not one of the allowed choices, and `UnsupportedDestinationError`
    when no built-in destination exists for the type. The error names the field but never its
    value, so a secret cannot leak through it.
    """
    config_class = registry.config_class_for(_destination_type(destination_type))
    if not isinstance(data, Mapping):
        raise DestinationConfigurationError(
            f"{destination_type} settings must be a mapping, got {type(data).__name__}",
            detail="The destination settings are not valid. Enter them again.",
        )

    try:
        return config_class.from_dict(dict(data))
    except UndecryptedConfigError as err:
        # The original exception carries no value, but drop it anyway: only field names leave here.
        raise DestinationConfigurationError(
            str(err), detail="The destination credentials could not be read. Enter them again."
        ) from None
    except (ConfigValueError, TypeError) as err:
        # A `TypeError` from the runtime names missing fields. Its cause, or the cause of a
        # `ConfigValueError`, can hold the refused value, so it does not travel with this error.
        message = f"Invalid {destination_type} settings: {err}"
        raise DestinationConfigurationError(message, detail=message) from None


def _destination_type(value: DestinationType | str) -> DestinationType:
    try:
        return DestinationType(value)
    except ValueError:
        raise UnsupportedDestinationError(
            f"Unknown destination type: '{value}'", detail="PostHog does not know this destination type."
        ) from None
