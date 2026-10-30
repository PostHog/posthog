"""The `source_config` of a warehouse alert on the alerts platform, and its native lifecycle.

A warehouse alert has no row of its own in this product. The platform creates and deletes it, and
keeps its destinations as `AlertDestination` rows that go with it.
"""

from collections.abc import Callable
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from products.alerts_platform.backend.facade.contracts import (
    GroupingMode,
    InvalidPlatformAlertEdit,
    NativeAlertLifecycle,
    PlatformAlertConfigurationEdit,
    SourceConfigSpec,
    SourceKind,
)
from products.warehouse_sources.backend.models.external_data_destination import ExternalDataDestination
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.sync_alerts.destinations import EVENT_IDS_BY_INCIDENT_ACTION
from products.warehouse_sources.backend.sync_alerts.wording import (
    DEFAULT_GROUP_BY,
    DESTINATION_ID_KEY,
    GROUPING_KEY_BY_GROUP_BY,
    destination_alerts_url,
    group_by_of,
    source_alerts_url,
)

# A sync status changes at most once per sync, so a few minutes of delay costs nothing a user notices.
CHECK_INTERVAL_MINUTES: Final = 5
MAX_SCOPED_IDS: Final = 100

_EMAIL_PROJECT_MEMBERS_HELP = (
    "Whether project members who get data pipeline error emails also get an email when this alert fires or resolves."
)


class WarehouseSourceAlertConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ids: list[UUID] = Field(
        default_factory=list,
        max_length=MAX_SCOPED_IDS,
        description="Warehouse sources the alert watches. Empty watches every source in the project, "
        "including sources added later.",
    )
    group_by: Literal["schema", "source"] = Field(
        default=DEFAULT_GROUP_BY,
        description="schema keeps one alert instance, and sends one message, per failing table. source keeps "
        "one per source, whatever number of its tables fail. The grouping must be by_result_labels with "
        "keys [schema_id] or [source_id] to match.",
    )
    include_billing_limits: bool = Field(
        default=False,
        description="Whether a table that stops syncing at the project's billing limit also fires the alert.",
    )
    email_project_members: bool = Field(default=False, description=_EMAIL_PROJECT_MEMBERS_HELP)


class WarehouseDestinationAlertConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_ids: list[UUID] = Field(
        default_factory=list,
        max_length=MAX_SCOPED_IDS,
        description="Warehouse destinations the alert watches. Empty watches every destination in the project, "
        "including destinations added later. The grouping must be by_result_labels with keys [destination_id].",
    )
    email_project_members: bool = Field(default=False, description=_EMAIL_PROJECT_MEMBERS_HELP)


def _validate_common(edit: PlatformAlertConfigurationEdit, grouping_key: str) -> None:
    if edit.grouping.mode != GroupingMode.BY_RESULT_LABELS or edit.grouping.keys != (grouping_key,):
        raise InvalidPlatformAlertEdit(
            "grouping", f'Set the grouping mode to by_result_labels with keys ["{grouping_key}"].'
        )
    # A sync status is the current state, not a series of samples, so there is nothing to count N of M over.
    for field_name in ("evaluation_periods", "datapoints_to_alarm"):
        if getattr(edit, field_name) != 1:
            raise InvalidPlatformAlertEdit(field_name, "Warehouse alerts check the current sync status. Set it to 1.")


def validate_source_edit(edit: PlatformAlertConfigurationEdit) -> None:
    _validate_common(edit, GROUPING_KEY_BY_GROUP_BY[group_by_of(edit.source_config)])


def validate_destination_edit(edit: PlatformAlertConfigurationEdit) -> None:
    _validate_common(edit, DESTINATION_ID_KEY)


def _require_ids_in_team(source_kind: SourceKind, team_id: int, edit: PlatformAlertConfigurationEdit) -> None:
    """The edit's ids must name this project's own rows. Validation cannot check this, because it has no team."""
    if source_kind == SourceKind.WAREHOUSE_SOURCE:
        ids = {str(item) for item in edit.source_config.get("source_ids") or []}
        found = {
            str(source_id)
            for source_id in ExternalDataSource.objects.filter(team_id=team_id, deleted=False, id__in=ids).values_list(
                "id", flat=True
            )
        }
        noun = "source"
    else:
        ids = {str(item) for item in edit.source_config.get("destination_ids") or []}
        found = {
            str(destination_id)
            for destination_id in ExternalDataDestination.objects.for_team(team_id, canonical=True)
            .filter(deleted=False, id__in=ids)
            .values_list("id", flat=True)
        }
        noun = "destination"
    if missing := sorted(ids - found):
        raise InvalidPlatformAlertEdit("source_config", f"No {noun} in this project has the ID {', '.join(missing)}.")


def _spec(
    source_kind: SourceKind,
    model: type[BaseModel],
    validate: Callable[[PlatformAlertConfigurationEdit], None],
    alert_url: Callable[[int, UUID], str],
) -> SourceConfigSpec:
    def check_in_team(*, team_id: int, edit: PlatformAlertConfigurationEdit) -> None:
        _require_ids_in_team(source_kind, team_id, edit)

    return SourceConfigSpec(
        model=model,
        validate=validate,
        check_in_team=check_in_team,
        # No `remove_destinations`, so the platform owns the destinations from the start.
        native=NativeAlertLifecycle(check_interval_minutes=CHECK_INTERVAL_MINUTES),
        incident_event_ids=EVENT_IDS_BY_INCIDENT_ACTION[source_kind],
        alert_url=alert_url,
    )


WAREHOUSE_SOURCE_ALERT_CONFIG: Final = _spec(
    SourceKind.WAREHOUSE_SOURCE, WarehouseSourceAlertConfig, validate_source_edit, source_alerts_url
)
WAREHOUSE_DESTINATION_ALERT_CONFIG: Final = _spec(
    SourceKind.WAREHOUSE_DESTINATION, WarehouseDestinationAlertConfig, validate_destination_edit, destination_alerts_url
)

ALERT_CONFIGS: Final[dict[SourceKind, SourceConfigSpec]] = {
    SourceKind.WAREHOUSE_SOURCE: WAREHOUSE_SOURCE_ALERT_CONFIG,
    SourceKind.WAREHOUSE_DESTINATION: WAREHOUSE_DESTINATION_ALERT_CONFIG,
}
