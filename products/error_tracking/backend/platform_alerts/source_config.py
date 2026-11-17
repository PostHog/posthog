"""The `source_config` of an error tracking alert on the alerts platform, and its native lifecycle.

An error tracking alert announces issue changes recorded in the issue change log, one instance per
issue. It has no row of its own in this product: the platform creates and deletes it, and its
destinations are `AlertDestination` rows that go with it.

Loaded on first use, never from `ready()`, because checking filters compiles HogQL.
"""

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from posthog.enums import LabeledStrEnum

from products.alerts_platform.backend.facade.contracts import (
    Grouping,
    GroupingMode,
    InvalidPlatformAlertEdit,
    NativeAlertLifecycle,
    PlatformAlertConfigurationEdit,
    SourceConfigSpec,
)
from products.error_tracking.backend.platform_alerts.wording import ISSUE_ID_LABEL, alert_url

CHECK_INTERVAL_MINUTES: Final = 1
# Every due alert is loaded each minute, so the count per team bounds that read. Error tracking's
# own alerts allow the same number.
MAX_ALERTS_PER_TEAM: Final = 50
ROLLOUT_FLAG: Final = "platform-alerts-source-error-tracking"
# Issue fields the native filters read but a change's snapshot does not carry. A filter on one would
# read it as unset, so a positive filter never matches and a negated one always does.
UNSUPPORTED_FILTER_KEYS: Final = frozenset({"description", "issue_description", "fingerprint"})

ISSUE_GROUPING: Final = Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=(ISSUE_ID_LABEL,))


class ErrorTrackingPlatformAlertTrigger(LabeledStrEnum):
    # Labels differ from the native alert's trigger choices, or the two classes would share one schema hash.
    ISSUE_CREATED = "issue_created", "A new issue is created"
    ISSUE_REOPENED = "issue_reopened", "A resolved or suppressed issue becomes active again"
    ISSUE_ASSIGNED = "issue_assigned", "An issue is assigned"


class ErrorTrackingPlatformAlertCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    triggers: list[ErrorTrackingPlatformAlertTrigger] = Field(
        min_length=1, description="The issue changes the alert announces. Each matching change is announced once."
    )


class ErrorTrackingPlatformAlertFilters(BaseModel):
    """Which issues and exceptions the alert announces, in the shape error tracking's destinations use."""

    model_config = ConfigDict(extra="forbid")

    properties: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Property filters on the exception event. Every filter must match.",
    )


class ErrorTrackingPlatformAlertConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filters: ErrorTrackingPlatformAlertFilters = Field(
        default_factory=ErrorTrackingPlatformAlertFilters, description="The issues and exceptions the alert announces."
    )
    condition: ErrorTrackingPlatformAlertCondition = Field(description="The issue changes the alert announces.")


def validate_error_tracking_edit(edit: PlatformAlertConfigurationEdit) -> None:
    if edit.grouping.mode != ISSUE_GROUPING.mode or edit.grouping.keys != ISSUE_GROUPING.keys:
        raise InvalidPlatformAlertEdit(
            "grouping",
            f"An error tracking alert groups by the `{ISSUE_ID_LABEL}` label, so each issue has its own instance.",
        )
    if edit.evaluation_periods != 1 or edit.datapoints_to_alarm != 1:
        raise InvalidPlatformAlertEdit("evaluation_periods", "An error tracking alert announces each change once.")


def check_filters_in_team(*, team_id: int, edit: PlatformAlertConfigurationEdit) -> None:
    """The filters must compile for the project, which validation cannot check without a team."""
    # Imported here, because it loads models and the HogQL compiler, which the config's import path avoids.
    from products.error_tracking.backend.logic.alerts import (  # noqa: PLC0415
        AlertValidationError,
        compile_alert_filters,
    )

    properties = edit.source_config.get("filters", {}).get("properties") or []
    unsupported = sorted(
        {leaf["key"] for leaf in properties if isinstance(leaf, dict) and leaf.get("key") in UNSUPPORTED_FILTER_KEYS}
    )
    if unsupported:
        raise InvalidPlatformAlertEdit(
            "source_config", f"Error tracking alerts can't filter on {', '.join(unsupported)} yet."
        )
    try:
        # The native alerts' own checks, so a leaf that would compile to match-all is refused here too.
        compile_alert_filters(team_id, {"properties": properties})
    except AlertValidationError as error:
        raise InvalidPlatformAlertEdit("source_config", str(error)) from error


ERROR_TRACKING_ALERT_CONFIG: Final = SourceConfigSpec(
    model=ErrorTrackingPlatformAlertConfig,
    validate=validate_error_tracking_edit,
    check_in_team=check_filters_in_team,
    native=NativeAlertLifecycle(
        check_interval_minutes=CHECK_INTERVAL_MINUTES,
        platform_destinations=True,
        max_per_team=MAX_ALERTS_PER_TEAM,
    ),
    alert_url=alert_url,
    rollout_flag=ROLLOUT_FLAG,
)
