import dataclasses


@dataclasses.dataclass(frozen=True)
class SpikeEventCleanupInputs:
    days_old: int = 30


@dataclasses.dataclass(frozen=True)
class SpikeEventCleanupResult:
    deleted_count: int
