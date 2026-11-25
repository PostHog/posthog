import dataclasses
from datetime import date, timedelta
from typing import Literal

from posthog.dataclasses import frozen

SessionStatus = Literal["exported", "deleted", "expired", "missing"]


def day_range(date_from: str, date_to: str) -> list[date]:
    first, last = date.fromisoformat(date_from), date.fromisoformat(date_to)
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


@frozen
class ExportTotals:
    exported: int = 0
    deleted: int = 0
    expired: int = 0
    missing: int = 0
    bytes: int = 0

    def add(self, other: "ExportTotals") -> "ExportTotals":
        return ExportTotals(
            **{f.name: getattr(self, f.name) + getattr(other, f.name) for f in dataclasses.fields(ExportTotals)}
        )


@frozen
class ExportDestination:
    role_arn: str
    bucket: str
    region: str
    prefix: str
    # A key ID in the role's account, or a key ARN. None writes with the bucket's default encryption.
    kms_key_id: str | None = None


@frozen
class ExportRecordingsInput:
    team_id: int
    destination: ExportDestination
    quote_id: str
    run_id: str
    # Inclusive UTC days, YYYY-MM-DD. A session belongs to the day it started on.
    date_from: str
    date_to: str
    # Holds the quote's session list, one file per day and shard. The run exports only those sessions.
    session_ids_prefix: str
    shards_per_day: int
    max_parallel_shards: int = 32
    # Run only these shards, each as "YYYY-MM-DD:shard", for example the failed shards of an earlier run.
    only_shards: tuple[str, ...] | None = None
    # Carried across continue-as-new.
    next_shard: int = 0
    totals: ExportTotals = ExportTotals()
    failed_shards: tuple[str, ...] = ()
    started_at: str | None = None


@frozen
class ExportShardInput:
    team_id: int
    destination: ExportDestination
    run_id: str
    day: str
    shard: int
    session_ids_prefix: str


@frozen
class DayViewportsInput:
    team_id: int
    run_id: str
    day: str
    shards_per_day: int
    session_ids_prefix: str


@frozen
class CheckDestinationInput:
    team_id: int
    destination: ExportDestination
    run_id: str


@frozen
class WriteSummaryInput:
    team_id: int
    destination: ExportDestination
    quote_id: str
    run_id: str
    shards_per_day: int
    started_at: str
    totals: ExportTotals
    failed_shards: tuple[str, ...]
    # Every shard of the quote ran and succeeded.
    complete: bool
