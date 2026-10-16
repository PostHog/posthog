"""The shape a logs alert takes in the platform's `source_config`.

Imported from `ready()` through the message wording, so it stays light: no models, no query layer.
"""

from typing import Any, Final

from products.alerts_platform.backend.facade.contracts import SOURCE_CONDITION_KEY, SourceConfigSpec

FILTERS_KEY: Final = "filters"


def logs_source_config(filters: object, condition: dict[str, Any]) -> dict[str, Any]:
    # Every reader of a stored copy calls `.get` on its filters, so a copy never stores another type.
    if not isinstance(filters, dict):
        raise TypeError(f"A logs alert's filters must be an object, got {type(filters).__name__}")
    return {FILTERS_KEY: filters, SOURCE_CONDITION_KEY: condition}


def filters_of(source_config: dict[str, Any]) -> dict[str, Any]:
    """The alert's filters, from the nested shape or the flat one.

    The flat shape holds the filters at the top level beside the condition. History rows in
    ClickHouse keep it permanently, and delivery builds messages from those rows.
    """
    if FILTERS_KEY in source_config:
        return source_config[FILTERS_KEY]
    return {key: value for key, value in source_config.items() if key != SOURCE_CONDITION_KEY}


def load_logs_source_config() -> SourceConfigSpec:
    from products.logs.backend.platform_source_config_schema import (  # noqa: PLC0415 - keeps posthog.schema off the startup path
        LOGS_SOURCE_CONFIG,
    )

    return LOGS_SOURCE_CONFIG
