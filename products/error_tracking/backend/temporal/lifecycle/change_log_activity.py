import uuid

from django.utils.dateparse import parse_datetime

import posthoganalytics
from temporalio import activity

from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.logic.issue_changes import (
    Created,
    IssueChangeData,
    Spiking,
    Status,
    StatusChanged,
    record_ingestion_change,
)
from products.error_tracking.backend.temporal.lifecycle.change_log import LifecycleChangeInputs

NIL_UUID = uuid.UUID(int=0)


def change_id(inputs: LifecycleChangeInputs) -> uuid.UUID:
    # One row per workflow: a retried activity or a replayed notification finds the row it wrote.
    return uuid.uuid5(uuid.NAMESPACE_OID, f"issue_change:{inputs.kind}:{inputs.notification_id}")


def change_data(inputs: LifecycleChangeInputs) -> IssueChangeData:
    match inputs.kind:
        case Created.kind:
            return Created()
        case StatusChanged.kind if inputs.previous_status is not None:
            return StatusChanged(previous=Status(inputs.previous_status))
        case Spiking.kind if inputs.computed_baseline is not None and inputs.current_bucket_value is not None:
            return Spiking(
                computed_baseline=inputs.computed_baseline, current_bucket_value=int(inputs.current_bucket_value)
            )
    raise ValueError(f"Incomplete inputs for a {inputs.kind} change")


def _event_uuid(value: str) -> uuid.UUID | None:
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return None
    return None if parsed == NIL_UUID else parsed


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def record_lifecycle_change_activity(inputs: LifecycleChangeInputs) -> None:
    record_ingestion_change(
        change_id=change_id(inputs),
        team_id=inputs.team_id,
        issue_id=uuid.UUID(inputs.issue_id),
        data=change_data(inputs),
        event_uuid=_event_uuid(inputs.event_uuid),
        event_timestamp=parse_datetime(inputs.event_timestamp),
    )


ACTIVITIES = [record_lifecycle_change_activity]
