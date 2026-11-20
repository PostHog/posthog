import dataclasses
from typing import Literal

from posthog.dataclasses import frozen

SessionStatus = Literal["exported", "deleted", "expired", "missing"]


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
    integration_id: int
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
    # Sessions not listed in the quote's session ID file are skipped. None exports every session.
    session_ids_key: str | None
    # Sessions that expired before the quote are left out, so the run exports what the quote priced.
    quoted_at: str
    shards_per_day: int = 16
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
    shards_per_day: int
    session_ids_key: str | None
    quoted_at: str


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
