"""Typed config runtime for warehouse sources.

The runtime lives in the `posthog-typed-config` package (`packages/typed-config`). This module
re-exports it so source configs and the generated config modules keep one import path.
"""

from typed_config import (
    META_KEY,
    REDACTED_VALUE_REPR,
    Config,
    ConfigProtocol,
    ConfigValueError,
    MetaConfig,
    UndecryptedConfigError,
    config,
    is_config,
    missing_field_error,
    str_to_bool,
    str_to_int,
    str_to_optional_int,
    str_to_optional_list,
    to_config,
    validate_config,
    value,
)

__all__ = [
    "META_KEY",
    "REDACTED_VALUE_REPR",
    "Config",
    "ConfigProtocol",
    "ConfigValueError",
    "MetaConfig",
    "UndecryptedConfigError",
    "config",
    "is_config",
    "missing_field_error",
    "str_to_bool",
    "str_to_int",
    "str_to_optional_int",
    "str_to_optional_list",
    "to_config",
    "validate_config",
    "value",
]
