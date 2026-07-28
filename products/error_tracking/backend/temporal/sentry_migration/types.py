import dataclasses


@dataclasses.dataclass(frozen=True)
class SentryMigrationInputs:
    migration_id: str
    team_id: int


@dataclasses.dataclass(frozen=True)
class MigrationContext:
    org_slug: str
    source_id: str


@dataclasses.dataclass(frozen=True)
class SyncCheckResult:
    ready: bool
    reason: str | None = None
    events_table: str | None = None
    issues_table: str | None = None


@dataclasses.dataclass(frozen=True)
class ImportTablesInputs:
    migration_id: str
    team_id: int
    events_table: str
    issues_table: str


@dataclasses.dataclass(frozen=True)
class PlanResult:
    issues_total: int
    events_total: int


@dataclasses.dataclass(frozen=True)
class ImportResult:
    events_emitted: int
    events_dropped: int


@dataclasses.dataclass(frozen=True)
class StatusSyncResult:
    resolved: int
    suppressed: int
    skipped_reason: str | None = None


@dataclasses.dataclass(frozen=True)
class SetStatusInputs:
    migration_id: str
    team_id: int
    status: str
    error: str | None = None
