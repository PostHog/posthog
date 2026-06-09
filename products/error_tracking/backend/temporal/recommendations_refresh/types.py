import dataclasses


@dataclasses.dataclass(frozen=True)
class RecommendationsRefreshInputs:
    # Only sweep teams that ingested at least one $exception within this window.
    lookback_days: int = 7
    # Teams per batch activity.
    batch_size: int = 100
    # How many batch activities run at once (bounds ClickHouse/Postgres load).
    max_concurrent_batches: int = 10


@dataclasses.dataclass(frozen=True)
class RefreshBatchInputs:
    team_ids: list[int]


@dataclasses.dataclass(frozen=True)
class RefreshBatchResult:
    teams_processed: int
    recommendations_kicked: int


@dataclasses.dataclass(frozen=True)
class RecommendationsRefreshResult:
    teams_total: int
    recommendations_kicked: int
    batches_failed: int
