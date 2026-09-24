from posthog.dataclasses import frozen


@frozen
class AutoResolveInputs:
    # Max teams per batch activity.
    batch_size: int = 50
    # Concurrent batches must stay bounded to limit database load.
    max_concurrent_batches: int = 3


@frozen
class AutoResolveBatchInputs:
    team_ids: list[int]


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
