import dataclasses


@dataclasses.dataclass(frozen=True)
class IssueChangeCleanupInputs:
    # The longest reader is a few days back: the platform alert check reads at most a day, and the
    # dispatcher retries within minutes. A week covers both with margin.
    days_old: int = 7
    batch_size: int = 10_000


@dataclasses.dataclass(frozen=True)
class IssueChangeCleanupResult:
    deleted_count: int
