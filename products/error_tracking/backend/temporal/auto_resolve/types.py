from posthog.dataclasses import frozen


@frozen
class AutoResolveInputs:
    # Max teams per batch activity.
    batch_size: int = 50
    # How many batch activities run at once (bounds ClickHouse/Postgres load).
    max_concurrent_batches: int = 3


@frozen
class TeamAutoResolveConfig:
    team_id: int
    # Kept on the wire for workflow history compatibility. Each activity reloads the setting.
    days: int | None


@frozen
class AutoResolveBatchInputs:
    teams: list[TeamAutoResolveConfig]


@frozen
class AutoResolveBatchResult:
    teams_processed: int
    teams_failed: int
    issues_resolved: int


@frozen
class AutoResolveResult:
    teams_total: int
    teams_failed: int
    issues_resolved: int
    batches_failed: int
