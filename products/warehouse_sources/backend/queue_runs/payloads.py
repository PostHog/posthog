"""The `sync.extract` job: what an enqueuer writes and what the extract consumer reads.

Whoever enqueues the job decides that the schema runs on the queue. The handler does not check
the scheduler flag again.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from posthog.dataclasses import frozen

SYNC_EXTRACT_KIND = "sync.extract"
EXTRACT_LANE = "extract"
# The workflow type that the log renderer and `resolve_log_source` use to route the run's logs.
EXTERNAL_DATA_JOB_WORKFLOW_TYPE = "external-data-job"


class SyncTrigger(enum.StrEnum):
    SCHEDULE = "schedule"
    MANUAL = "manual"


def group_key(team_id: int, schema_id: uuid.UUID | str) -> str:
    """The lease key of a schema on the extract lane. One run of a schema executes at a time."""
    return f"{team_id}:{schema_id}"


def scheduled_workflow_id(schema_id: uuid.UUID | str, fire_at: datetime) -> str:
    """The id a Temporal schedule gives the run it fires at `fire_at`.

    The log router takes the schema id from the front of this id, so the shape must not change.
    """
    return f"{schema_id}-{fire_at:%Y-%m-%dT%H:%M:%SZ}"


def manual_workflow_id(schema_id: uuid.UUID | str, at: datetime) -> str:
    return f"{schema_id}-queue-{int(at.timestamp())}"


@frozen
class SyncExtractPayload:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID
    trigger: SyncTrigger
    billable: bool
    # None lets the run read the schema's own reset flag, as a Temporal run does.
    reset_pipeline: bool | None
    # Stamped on the job row and on every queued batch, so the loader and the log router treat
    # the run like a Temporal run.
    workflow_id: str
    # The schedule boundary a scheduled run fires for. None for a manual run.
    due_at: datetime | None = None

    @property
    def group_key(self) -> str:
        return group_key(self.team_id, self.schema_id)

    def to_json(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "schema_id": str(self.schema_id),
            "source_id": str(self.source_id),
            "trigger": self.trigger.value,
            "billable": self.billable,
            "reset_pipeline": self.reset_pipeline,
            "workflow_id": self.workflow_id,
            "due_at": self.due_at.isoformat() if self.due_at is not None else None,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SyncExtractPayload:
        due_at = data.get("due_at")
        return cls(
            team_id=int(data["team_id"]),
            schema_id=uuid.UUID(str(data["schema_id"])),
            source_id=uuid.UUID(str(data["source_id"])),
            trigger=SyncTrigger(data["trigger"]),
            billable=bool(data["billable"]),
            reset_pipeline=data.get("reset_pipeline"),
            workflow_id=str(data["workflow_id"]),
            due_at=datetime.fromisoformat(due_at) if due_at else None,
        )
