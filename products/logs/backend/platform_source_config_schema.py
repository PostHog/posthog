"""The schema a logs alert's `source_config` takes in the alerts platform's API, and the rules for
a whole edit.

Loaded on first use through `load_logs_source_config`, never from `ready()`, because it is built
on `posthog.schema`.
"""

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from posthog.schema import LogsAlertFilters

from products.alerts_platform.backend.facade.contracts import (
    GroupingMode,
    InvalidPlatformAlertEdit,
    PlatformAlertConfigurationEdit,
    SourceConfigSpec,
)
from products.logs.backend.alert_check_query import GROUPABLE_LOGS_COLUMNS
from products.logs.backend.models import LogsAlertConfiguration

WindowMinutes = Literal[5, 10, 15, 30, 60]
ALLOWED_WINDOW_MINUTES: frozenset[int] = frozenset(get_args(WindowMinutes))


class LogsPlatformAlertCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold_count: int = Field(
        ...,
        ge=0,
        description="Number of matching log entries in the window that breaches the threshold. "
        "Use 0 with the above operator to fire on any matching log.",
    )
    threshold_operator: LogsAlertConfiguration.ThresholdOperator = Field(
        ..., description="Whether the alert fires when the count is above or below the threshold."
    )
    window_minutes: WindowMinutes = Field(..., description="Time window in minutes over which logs are counted.")


class LogsPlatformAlertSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filters: LogsAlertFilters = Field(
        ...,
        description="The logs the alert counts: severityLevels, serviceNames, or a filterGroup of property "
        "filters. An enabled alert needs at least one.",
    )
    condition: LogsPlatformAlertCondition = Field(..., description="The bound the count is checked against.")


def validate_logs_edit(edit: PlatformAlertConfigurationEdit) -> None:
    filters = edit.source_config["filters"]
    if edit.enabled and not any(filters.get(key) for key in ("severityLevels", "serviceNames", "filterGroup")):
        raise InvalidPlatformAlertEdit(
            "source_config", "An enabled alert needs at least one of severityLevels, serviceNames or filterGroup."
        )
    if edit.grouping.mode == GroupingMode.SINGLE:
        return
    if unknown := set(edit.grouping.keys) - GROUPABLE_LOGS_COLUMNS:
        raise InvalidPlatformAlertEdit(
            "grouping",
            f"A logs alert can only group by {', '.join(sorted(GROUPABLE_LOGS_COLUMNS))}, "
            f"not {', '.join(sorted(unknown))}.",
        )
    # A group with no matching log returns no row, so a service gone silent, the case a `below`
    # alert exists for, is never seen unless it was already open.
    if edit.source_config["condition"]["threshold_operator"] != LogsAlertConfiguration.ThresholdOperator.ABOVE:
        raise InvalidPlatformAlertEdit("grouping", "A grouped logs alert can only alert above a threshold.")


LOGS_SOURCE_CONFIG = SourceConfigSpec(model=LogsPlatformAlertSourceConfig, validate=validate_logs_edit)
