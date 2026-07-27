import dataclasses
from enum import StrEnum


@dataclasses.dataclass(frozen=True)
class LifecycleIssueSnapshot:
    name: str | None
    description: str | None
    status: str
    created_at: str


class SpikeEventPersistenceStatus(StrEnum):
    INSERTED = "inserted"
    ALREADY_PERSISTED = "already_persisted"
    MISSING_ISSUE = "missing_issue"
