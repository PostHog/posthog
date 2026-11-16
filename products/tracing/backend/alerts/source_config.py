"""The `source_config` of a traces alert on the alerts platform, and its native lifecycle.

A traces alert has no row of its own in this product. The platform creates and deletes it, and its
destinations are `AlertDestination` rows that go with it.

Loaded on first use, never from `ready()`, because it is built on `posthog.schema`.
"""

from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from posthog.schema import PropertyGroupFilter

from posthog.enums import LabeledStrEnum

from products.alerts_platform.backend.facade.contracts import (
    GroupingMode,
    InvalidPlatformAlertEdit,
    NativeAlertLifecycle,
    PlatformAlertConfigurationEdit,
    SourceConfigSpec,
)
from products.tracing.backend.alerts.destinations import EVENT_IDS_BY_INCIDENT_ACTION
from products.tracing.backend.alerts.group_columns import GROUP_COLUMNS
from products.tracing.backend.alerts.wording import alert_url

CHECK_INTERVAL_MINUTES: Final = 1
# Every due alert is loaded each minute, so the count per team bounds that read.
MAX_ALERTS_PER_TEAM: Final = 20

Measure = Literal["request_count", "error_count", "error_rate", "latency"]
Percentile = Literal[50, 90, 95, 99]
WindowMinutes = Literal[5, 10, 15, 30, 60]


class TracesAlertThresholdOperator(LabeledStrEnum):
    # Labels differ from the logs alert's operator choices, or the two classes would share one schema hash.
    ABOVE = "above", "Above the threshold"
    BELOW = "below", "Below the threshold"


class TracesAlertFilters(BaseModel):
    """The requests an alert measures, in the tracing scene's filter shape."""

    model_config = ConfigDict(extra="forbid")

    serviceNames: list[str] = Field(default_factory=list, description="Services whose requests the alert measures.")
    filterGroup: PropertyGroupFilter | None = Field(
        default=None, description="Span, span attribute and resource attribute filters, as the tracing scene sends."
    )


class TracesPlatformAlertCondition(BaseModel):
    # A NaN threshold compares false with every value, so a saved alert could never fire.
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    measure: Measure = Field(
        description="What the alert measures over requests: their count, the count with an error status, "
        "the share with an error status, or a latency percentile. A request is a trace root, server or "
        "consumer span."
    )
    percentile: Percentile | None = Field(default=None, description="The latency percentile. Required for latency.")
    threshold: float = Field(
        ge=0,
        description="The bound: a count for request_count and error_count, a fraction from 0 to 1 for "
        "error_rate, milliseconds for latency.",
    )
    threshold_operator: TracesAlertThresholdOperator = Field(description="Whether the alert fires above or below it.")
    window_minutes: WindowMinutes = Field(description="Time window in minutes that each check measures.")

    @model_validator(mode="after")
    def _check_measure(self) -> Self:
        if (self.measure == "latency") != (self.percentile is not None):
            raise ValueError("A latency condition needs a percentile, and no other measure takes one.")
        if self.measure == "error_rate" and self.threshold > 1:
            raise ValueError("An error rate threshold is a fraction from 0 to 1.")
        return self


class TracesPlatformAlertConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filters: TracesAlertFilters = Field(
        default_factory=TracesAlertFilters, description="The requests the alert measures."
    )
    condition: TracesPlatformAlertCondition = Field(description="The bound the measure is checked against.")


def validate_traces_edit(edit: PlatformAlertConfigurationEdit) -> None:
    if edit.grouping.mode == GroupingMode.SINGLE:
        return
    if unknown := set(edit.grouping.keys) - GROUP_COLUMNS.keys():
        raise InvalidPlatformAlertEdit(
            "grouping",
            f"A traces alert can only group by {', '.join(sorted(GROUP_COLUMNS))}, not {', '.join(sorted(unknown))}.",
        )
    # A group with no requests returns no row, so a service gone silent, the case a `below` alert
    # exists for, is never seen unless it was already open.
    if edit.source_config["condition"]["threshold_operator"] != "above":
        raise InvalidPlatformAlertEdit("grouping", "A grouped traces alert can only alert above a threshold.")
    # Operation names are often unbounded (a route with ids in it), so a project-wide split by
    # operation overflows `max_instances` and holds a quantile state per operation in memory.
    if "name" in edit.grouping.keys and not edit.source_config.get("filters", {}).get("serviceNames"):
        raise InvalidPlatformAlertEdit("grouping", "Grouping by operation needs at least one service filter.")


TRACES_ALERT_CONFIG: Final = SourceConfigSpec(
    model=TracesPlatformAlertConfig,
    validate=validate_traces_edit,
    # No `remove_destinations`, so the alert's destinations are `AlertDestination` rows from the start.
    native=NativeAlertLifecycle(check_interval_minutes=CHECK_INTERVAL_MINUTES, max_per_team=MAX_ALERTS_PER_TEAM),
    incident_event_ids=EVENT_IDS_BY_INCIDENT_ACTION,
    alert_url=alert_url,
    rollout_flag="platform-alerts-source-traces",
)
