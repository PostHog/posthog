import dataclasses


@dataclasses.dataclass(frozen=True)
class RecommendationsRefreshInputs:
    # Only sweep teams that ingested at least one $exception within this window.
    lookback_days: int = 7
    # Max teams per batch activity.
    batch_size: int = 200
    # Max summed exception volume per batch. The batched ClickHouse query's cost scales
    # with event volume rather than team count, so this keeps memory bounded when
    # high-volume teams land in the same batch.
    max_events_per_batch: int = 20_000_000
    # How many batch activities run at once (bounds ClickHouse/Postgres load).
    max_concurrent_batches: int = 5


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
