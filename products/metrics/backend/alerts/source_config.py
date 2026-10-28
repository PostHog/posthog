"""The `source_config` of a metrics alert on the alerts platform, and its native lifecycle.

A metrics alert has no row of its own in this product. The platform creates and deletes it, and its
configuration id is the id its destinations match on.
"""

from typing import Final, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from products.alerts.backend.facade.destinations import soft_delete_all_alert_destinations
from products.alerts_platform.backend.facade.contracts import (
    NativeAlertLifecycle,
    PlatformAlertConfigurationEdit,
    SourceConfigSpec,
)
from products.metrics.backend.alerts.destinations import EVENT_IDS, EVENT_IDS_BY_INCIDENT_ACTION
from products.metrics.backend.alerts.wording import alert_url

# A metrics alert checks the latest value of each series, so it runs as often as the platform allows.
CHECK_INTERVAL_MINUTES: Final = 1
MAX_QUERY_LENGTH: Final = 10_000

Operator = Literal[">", ">=", "<", "<=", "==", "!="]


class MetricsAlertCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["threshold", "present"] = Field(
        default="threshold",
        description="threshold compares each series' latest value with `threshold`. present fires for every "
        "series the query returns, for a query that already filters to the series in breach.",
    )
    operator: Operator | None = Field(
        default=None, description="How a series' value compares with `threshold`. Required for a threshold."
    )
    threshold: float | None = Field(
        default=None, description="The value a series is compared with. Required for a threshold."
    )

    @model_validator(mode="after")
    def _check_kind(self) -> Self:
        if self.kind == "threshold" and (self.operator is None or self.threshold is None):
            raise ValueError("A threshold condition needs an operator and a threshold.")
        if self.kind == "present" and (self.operator is not None or self.threshold is not None):
            raise ValueError("A present condition takes no operator or threshold.")
        return self


class MetricsAlertConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        min_length=1,
        max_length=MAX_QUERY_LENGTH,
        description="A PromQL expression over this project's metrics. Each series it returns is one group. "
        "For a threshold condition, leave the comparison out of the expression.",
    )
    condition: MetricsAlertCondition = Field(description="When a series is in breach.")


def _validate_edit(edit: PlatformAlertConfigurationEdit) -> None:
    # The model holds every rule, so an edit adds none.
    return None


def _remove_destinations(*, team_id: int, configuration_id: UUID) -> None:
    soft_delete_all_alert_destinations(team_id=team_id, alert_id=str(configuration_id), allowed_event_ids=EVENT_IDS)


METRICS_ALERT_CONFIG: Final = SourceConfigSpec(
    model=MetricsAlertConfig,
    validate=_validate_edit,
    native=NativeAlertLifecycle(
        check_interval_minutes=CHECK_INTERVAL_MINUTES, remove_destinations=_remove_destinations
    ),
    incident_event_ids=EVENT_IDS_BY_INCIDENT_ACTION,
    alert_url=alert_url,
)
