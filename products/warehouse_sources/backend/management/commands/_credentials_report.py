from django.core.management.base import OutputWrapper

from products.warehouse_sources.backend.logic.source_credentials_sync import BackfillCounts


def print_backfill_counts(stdout: OutputWrapper, counts: BackfillCounts, labels: dict[str, str] | None = None) -> None:
    """One line per source type and outcome, then totals. Prints counts only, never field values."""
    labels = labels or {}
    totals: dict[str, int] = {}
    for (source_type, outcome), count in sorted(counts.items()):
        name = labels.get(outcome, outcome)
        stdout.write(f"{source_type}: {name}={count}")
        totals[name] = totals.get(name, 0) + count
    stdout.write("total: " + (" ".join(f"{name}={count}" for name, count in sorted(totals.items())) or "no sources"))
