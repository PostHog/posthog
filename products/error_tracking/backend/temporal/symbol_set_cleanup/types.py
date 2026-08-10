import dataclasses


@dataclasses.dataclass(frozen=True)
class SymbolSetCleanupInputs:
    days_old: int = 30
    delete_unused: bool = True
    total_per_run: int = 1000000
    batch_size: int = 10000
    # Workers contend rather than divide: they take `FOR UPDATE SKIP LOCKED` over the same
    # ordered range, so each one pays the full traversal and skips what the others hold.
    # `total_per_run` caps throughput regardless, so fewer workers spend less to reach it.
    parallelism: int = 4
    dry_run: bool = False


@dataclasses.dataclass(frozen=True)
class SymbolSetCleanupResult:
    objects_processed: int
    objects_deleted: int
    objects_failed: int
    storage_objects_failed: int = 0
    eligible_count: int | None = None
