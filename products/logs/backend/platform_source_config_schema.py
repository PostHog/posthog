"""The schema a logs alert's `source_config` takes in the alerts platform's API, and the rules for
a whole edit.

Loaded on first use through `load_logs_source_config`, never from `ready()`, because it is built
on `posthog.schema`.
"""

from pydantic import BaseModel, ConfigDict, Field

from posthog.schema import LogsAlertFilters

from products.alerts_platform.backend.facade.contracts import (
    MAX_STORED_INTEGER,
    GroupingMode,
    InvalidPlatformAlertEdit,
    PlatformAlertConfigurationEdit,
    SourceConfigSpec,
)
from products.logs.backend.alert_deletion import delete_platform_owned
from products.logs.backend.alert_group_columns import grouping_problem
from products.logs.backend.alert_source_cycle import EVENT_IDS_BY_INCIDENT_ACTION
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_ownership import create_platform_owned, mirror_platform_edit
from products.logs.backend.platform_source_config import WindowMinutes, has_any_filter, logs_alert_url


class LogsPlatformAlertCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold_count: int = Field(
        ...,
        ge=0,
        # The logs row stores it in an `integer` column, which a mirrored edit writes.
        le=MAX_STORED_INTEGER,
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
    # The logs API's rule: a draft may hold no filters, but any filters it holds must narrow something.
    if (edit.enabled or filters) and not has_any_filter(filters):
        raise InvalidPlatformAlertEdit(
            "source_config", "At least one filter is required (severityLevels, serviceNames, or filterGroup)."
        )
    if edit.grouping.mode == GroupingMode.SINGLE:
        return
    if problem := grouping_problem(edit.grouping.keys, edit.source_config["condition"]["threshold_operator"]):
        raise InvalidPlatformAlertEdit("grouping", problem)


LOGS_SOURCE_CONFIG = SourceConfigSpec(
    model=LogsPlatformAlertSourceConfig,
    validate=validate_logs_edit,
    mirror=mirror_platform_edit,
    create=create_platform_owned,
    delete=delete_platform_owned,
    incident_event_ids=EVENT_IDS_BY_INCIDENT_ACTION,
    alert_url=logs_alert_url,
)
