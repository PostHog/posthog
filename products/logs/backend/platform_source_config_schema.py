"""The schema a logs alert's `source_config` takes in the alerts platform's API, and the rules for
a whole edit.

Loaded on first use through `load_logs_source_config`, never from `ready()`, because it is built
on `posthog.schema`.
"""

from uuid import UUID

from django.utils import timezone

from pydantic import BaseModel, ConfigDict, Field

from posthog.schema import LogsAlertFilters

from products.alerts_platform.backend.facade.contracts import (
    GroupingMode,
    InvalidPlatformAlertEdit,
    PlatformAlertConfigurationEdit,
    SourceConfigSpec,
)
from products.logs.backend.alert_group_columns import grouping_problem
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_source_config import WindowMinutes, has_any_filter


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
    # The logs API's rule: a draft may hold no filters, but any filters it holds must narrow something.
    if (edit.enabled or filters) and not has_any_filter(filters):
        raise InvalidPlatformAlertEdit(
            "source_config", "At least one filter is required (severityLevels, serviceNames, or filterGroup)."
        )
    if edit.grouping.mode == GroupingMode.SINGLE:
        return
    if problem := grouping_problem(edit.grouping.keys, edit.source_config["condition"]["threshold_operator"]):
        raise InvalidPlatformAlertEdit("grouping", problem)


class _LogsEditMirror:
    """Writes an edit made through the platform API onto the logs row, so the logs page, the shadow
    evaluation and a rollback all read what the platform runs."""

    def lock(self, legacy_configuration_id: UUID) -> None:
        LogsAlertConfiguration.objects.select_for_update().filter(id=legacy_configuration_id).exists()

    def write(self, legacy_configuration_id: UUID, edit: PlatformAlertConfigurationEdit) -> None:
        _write_logs_row(LogsAlertConfiguration.objects.get(id=legacy_configuration_id), edit)


def _write_logs_row(alert: LogsAlertConfiguration, edit: PlatformAlertConfigurationEdit) -> None:
    condition = edit.source_config["condition"]
    if edit.enabled and alert.first_enabled_at is None:
        alert.first_enabled_at = timezone.now()
    alert.name = edit.name
    alert.enabled = edit.enabled
    alert.filters = edit.source_config["filters"]
    alert.threshold_count = condition["threshold_count"]
    alert.threshold_operator = condition["threshold_operator"]
    alert.window_minutes = condition["window_minutes"]
    alert.evaluation_periods = edit.evaluation_periods
    alert.datapoints_to_alarm = edit.datapoints_to_alarm
    alert.cooldown_minutes = edit.cooldown_minutes
    alert.schedule_restriction = edit.schedule_restriction
    alert.save(
        update_fields=[
            "first_enabled_at",
            "name",
            "enabled",
            "filters",
            "threshold_count",
            "threshold_operator",
            "window_minutes",
            "evaluation_periods",
            "datapoints_to_alarm",
            "cooldown_minutes",
            "schedule_restriction",
            "updated_at",
        ]
    )


LOGS_SOURCE_CONFIG = SourceConfigSpec(
    model=LogsPlatformAlertSourceConfig, validate=validate_logs_edit, mirror=_LogsEditMirror()
)
