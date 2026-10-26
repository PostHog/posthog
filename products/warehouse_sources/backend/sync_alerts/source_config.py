"""The `source_config` of a warehouse alert on the alerts platform, and the hooks that create and delete one.

A warehouse alert has no row of its own in this product. The platform's create path copies a source
row it is given the id of, so the create hook mints a UUID to stand in for that row, copies the alert
in under it, and hands the copy to the platform at once. Destinations match on the same UUID.
"""

from collections.abc import Callable
from typing import Final, Literal
from uuid import UUID, uuid4

from django.utils import timezone

from pydantic import BaseModel, ConfigDict, Field

from products.alerts.backend.facade.destinations import soft_delete_all_alert_destinations
from products.alerts_platform.backend.facade.api import (
    close_owned_firings_now,
    delete_owned_copy,
    take_ownership,
    upsert_configuration,
)
from products.alerts_platform.backend.facade.contracts import (
    GroupingMode,
    InvalidPlatformAlertEdit,
    PlatformAlertConfigurationEdit,
    PlatformAlertUpsert,
    PlatformOwnershipHandover,
    SourceConfigSpec,
    SourceCreate,
    SourceDelete,
    SourceEditMirror,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.warehouse_sources.backend.models.external_data_destination import ExternalDataDestination
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.sync_alerts.destinations import EVENT_IDS, EVENT_IDS_BY_INCIDENT_ACTION
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


def _create(source_kind: SourceKind) -> SourceCreate:
    def create(*, team_id: int, edit: PlatformAlertConfigurationEdit, created_by_id: int | None) -> UUID:
        _require_ids_in_team(source_kind, team_id, edit)
        anchor = uuid4()
        now = timezone.now()
        upsert_configuration(
            PlatformAlertUpsert(
                legacy_configuration_id=anchor,
                team_id=team_id,
                name=edit.name,
                enabled=edit.enabled,
                source_kind=source_kind,
                source_config=edit.source_config,
                check_interval_minutes=CHECK_INTERVAL_MINUTES,
                evaluation_periods=edit.evaluation_periods,
                datapoints_to_alarm=edit.datapoints_to_alarm,
                cooldown_minutes=edit.cooldown_minutes,
                schedule_restriction=edit.schedule_restriction,
                next_check_at=now,
                snooze_until=None,
                grouping=edit.grouping,
            )
        )
        take_ownership(
            PlatformOwnershipHandover(
                legacy_configuration_id=anchor,
                team_id=team_id,
                state=PlatformAlertState.NOT_FIRING,
                last_notified_at=None,
                consecutive_failures=0,
                next_check_at=now,
                at=now,
            )
        )
        return anchor

    return create


def _mirror(source_kind: SourceKind) -> SourceEditMirror:
    def mirror(
        *, team_id: int, legacy_configuration_id: UUID
    ) -> Callable[[PlatformAlertConfigurationEdit], None] | None:
        # There is no source row to write. The edit's transaction still rolls back when this raises.
        return lambda edit: _require_ids_in_team(source_kind, team_id, edit)

    return mirror


def _delete(source_kind: SourceKind) -> SourceDelete:
    def delete(*, team_id: int, legacy_configuration_id: UUID) -> None:
        # Before the destinations go, so an incident manager still gets the resolve for an open firing.
        close_owned_firings_now(team_id=team_id, legacy_configuration_id=legacy_configuration_id)
        soft_delete_all_alert_destinations(
            team_id=team_id, alert_id=str(legacy_configuration_id), allowed_event_ids=EVENT_IDS[source_kind]
        )
        delete_owned_copy(team_id=team_id, legacy_configuration_id=legacy_configuration_id)

    return delete


WAREHOUSE_SOURCE_ALERT_CONFIG: Final = SourceConfigSpec(
    model=WarehouseSourceAlertConfig,
    validate=validate_source_edit,
    mirror=_mirror(SourceKind.WAREHOUSE_SOURCE),
    create=_create(SourceKind.WAREHOUSE_SOURCE),
    delete=_delete(SourceKind.WAREHOUSE_SOURCE),
    incident_event_ids=EVENT_IDS_BY_INCIDENT_ACTION[SourceKind.WAREHOUSE_SOURCE],
    alert_url=source_alerts_url,
)

WAREHOUSE_DESTINATION_ALERT_CONFIG: Final = SourceConfigSpec(
    model=WarehouseDestinationAlertConfig,
    validate=validate_destination_edit,
    mirror=_mirror(SourceKind.WAREHOUSE_DESTINATION),
    create=_create(SourceKind.WAREHOUSE_DESTINATION),
    delete=_delete(SourceKind.WAREHOUSE_DESTINATION),
    incident_event_ids=EVENT_IDS_BY_INCIDENT_ACTION[SourceKind.WAREHOUSE_DESTINATION],
    alert_url=destination_alerts_url,
)

ALERT_CONFIGS: Final[dict[SourceKind, SourceConfigSpec]] = {
    SourceKind.WAREHOUSE_SOURCE: WAREHOUSE_SOURCE_ALERT_CONFIG,
    SourceKind.WAREHOUSE_DESTINATION: WAREHOUSE_DESTINATION_ALERT_CONFIG,
}
