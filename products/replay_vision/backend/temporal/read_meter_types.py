"""Types and pure throttle math for the scanner read metering — a dependency leaf, so the
sweep activity can use the throttle without importing the workflow module."""

import datetime as dt

from pydantic import BaseModel

from products.replay_vision.backend.temporal.constants import SWEEP_READ_BUDGET_BYTES_24H, SWEEP_THROTTLE_MAX_FACTOR


class MeterScannerReadsInputs(BaseModel, frozen=True):
    pass


class MeterScannerReadsResult(BaseModel, frozen=True):
    scanners_updated: int = 0


def sweep_spend_bytes_24h(read_bytes_by_hour: dict[str, int] | None, now: dt.datetime) -> int:
    """Trailing-24h read spend from the metered hour buckets; tolerates stale, unpruned entries."""
    if not read_bytes_by_hour:
        return 0
    cutoff = now - dt.timedelta(hours=24)
    total = 0
    for hour_iso, read_bytes in read_bytes_by_hour.items():
        try:
            hour = dt.datetime.fromisoformat(hour_iso)
        except ValueError:
            continue
        if hour >= cutoff:
            total += int(read_bytes)
    return total


def sweep_throttle_factor(spend_bytes: int, override: int | None) -> int:
    """Cadence-stretch multiplier: 1 means sweep normally, N means sweep every N schedule intervals."""
    if override is not None:
        return max(1, min(override, SWEEP_THROTTLE_MAX_FACTOR))
    return max(1, min(round(spend_bytes / SWEEP_READ_BUDGET_BYTES_24H), SWEEP_THROTTLE_MAX_FACTOR))
