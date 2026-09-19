import dataclasses

SYMBOL_SET_CLEANUP_BUCKET_COUNT = 256


@dataclasses.dataclass(frozen=True)
class SymbolSetCleanupInputs:
    days_old: int = 30
    delete_unused: bool = True
    total_per_run: int = 1000000
    batch_size: int = 10000
    # Runtime workers divide the fixed indexed buckets, so parallelism can change without rebuilding the index.
    parallelism: int = 4
    dry_run: bool = False
    bucket_worker_index: int = 0
    bucket_worker_count: int = 1
    bucket_offset: int = 0
    # A run sweeps a rotating slice of the buckets instead of all of them. Every bucket costs an index
    # descent even when it holds nothing to delete, and the retention cutoff is 30 days, so there is no
    # value in probing all 256 every 30 minutes.
    buckets_per_run: int = 32

    def sweep_size(self) -> int:
        return max(1, min(self.buckets_per_run, SYMBOL_SET_CLEANUP_BUCKET_COUNT))


@dataclasses.dataclass(frozen=True)
class SymbolSetCleanupResult:
    objects_processed: int
    objects_deleted: int
    objects_failed: int
    storage_objects_failed: int = 0
    eligible_count: int | None = None
