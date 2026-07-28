import dataclasses


@dataclasses.dataclass(frozen=True)
class MigrationInputs:
    migration_id: str
    team_id: int


@dataclasses.dataclass(frozen=True)
class MigrationContext:
    source_type: str
    source_id: str


@dataclasses.dataclass(frozen=True)
class SyncCheckResult:
    ready: bool
    reason: str | None = None
    # Adapter schema role -> resolved warehouse table name.
    tables: dict[str, str] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class ImportTablesInputs:
    migration_id: str
    team_id: int
    tables: dict[str, str]


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
