"""The base class and the helpers that generated destination configs use.

Built on the shared `typed_config` runtime. Its `repr` redacts fields whose name looks secret,
and the generator also hides every field the spec marks as secret, so a config never shows a
credential in a log line or an error report.
"""

from collections.abc import Callable, Iterable
from typing import Any, ClassVar

import typed_config as config

from ..enums import DestinationType


class DestinationConfig(config.Config):
    """The connection settings of one destination type.

    Each generated subclass sets `destination_type`, so a `DestinationConnection` knows which
    destination to build from its config alone.
    """

    destination_type: ClassVar[DestinationType]


def text(value: Any) -> str:
    """A converter for a required text value. It refuses a value that is not a string or is blank."""
    if not isinstance(value, str):
        raise TypeError(f"expected a string, got {type(value).__name__}")
    if not value.strip():
        raise ValueError("expected a value that is not blank")
    return value


def optional_text(value: Any) -> str | None:
    """A converter for an optional text value. It accepts None and refuses other non-strings."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"expected a string, got {type(value).__name__}")
    return value


def choice(*options: str, optional: bool = False) -> Callable[[Any], str | None]:
    """A converter that accepts only one of `options`, and None when `optional`."""

    def convert(value: Any) -> str | None:
        if value is None and optional:
            return None
        if value not in options:
            # The message names the options only: the refused value can be anything the user typed.
            raise ValueError(f"expected one of {', '.join(options)}")
        return value

    return convert


def require_fields(instance: object, names: Iterable[str]) -> None:
    """Raise `ConfigValueError` for the first of `names` that is None or blank on `instance`.

    Generated classes call this for fields that are required only in one select option or only
    when a switch group is on.
    """
    for name in names:
        value = getattr(instance, name)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise config.ConfigValueError(f"Config field '{name}' is required")
