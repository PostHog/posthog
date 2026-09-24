import dataclasses


@dataclasses.dataclass(frozen=True)
class AutoResolveInputs:
    # Max teams per batch activity.
    batch_size: int = 50
    # How many batch activities run at once (bounds ClickHouse/Postgres load).
    max_concurrent_batches: int = 3


@dataclasses.dataclass(frozen=True)
class TeamAutoResolveConfig:
    team_id: int
    days: int


@dataclasses.dataclass(frozen=True)
class AutoResolveBatchInputs:
    teams: list[TeamAutoResolveConfig]


@dataclasses.dataclass(frozen=True)
class AutoResolveBatchResult:
    teams_processed: int
    teams_failed: int
    issues_resolved: int


@dataclasses.dataclass(frozen=True)
class AutoResolveResult:
    teams_total: int
    teams_failed: int
    issues_resolved: int
    batches_failed: int
