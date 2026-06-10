import dataclasses


@dataclasses.dataclass(frozen=True)
class SymbolSetCleanupInputs:
    days_old: int = 30
    delete_unused: bool = True
    total_per_run: int = 50000
    batch_size: int = 2000
    dry_run: bool = False


@dataclasses.dataclass(frozen=True)
class SymbolSetCleanupResult:
    objects_processed: int
    objects_deleted: int
    objects_failed: int
    eligible_count: int | None = None
