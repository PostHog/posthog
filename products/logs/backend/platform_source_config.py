"""The shape a logs alert takes in the platform's `source_config`.

Imported from `ready()` through the message wording, so it stays light: no models, no query layer.
"""

from typing import Any, Final, Literal, get_args

from posthog.utils import absolute_uri

from products.alerts_platform.backend.facade.contracts import SOURCE_CONDITION_KEY, SourceConfigSpec

FILTERS_KEY: Final = "filters"
# The filter fields that narrow which logs an alert counts. An alert with none of them counts all logs.
LOGS_FILTER_KEYS: Final = ("severityLevels", "serviceNames", "filterGroup")

WindowMinutes = Literal[5, 10, 15, 30, 60]
ALLOWED_WINDOW_MINUTES: Final[frozenset[int]] = frozenset(get_args(WindowMinutes))


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


def has_any_filter(filters: dict[str, Any]) -> bool:
    return any(filters.get(key) for key in LOGS_FILTER_KEYS)


def logs_alert_url(team_id: int, alert_id: object) -> str:
    """The alert's page in the logs product, which messages and incidents link to."""
    return absolute_uri(f"/project/{team_id}/logs/alerts/{alert_id}")
