import dataclasses


@dataclasses.dataclass(frozen=True)
class WeeklyDigestInputs:
    # dry_run builds digests without POSTing to the delivery workflow or stamping
    # MessagingRecords. It defaults to True so an input-less manual run (e.g. from the
    # Temporal UI) can never send real digests — only the registered schedule and
    # deliberate manual runs pass dry_run=False. org_ids bypasses discovery for
    # targeted manual runs.
    dry_run: bool = True
    org_ids: list[str] | None = None
    # How many per-org activities run at once (bounds ClickHouse load and webhook rate).
    max_concurrent: int = 10
    # Total executions per org activity: initial run + 5 retries. The final attempt sends
    # partial digests instead of deferring recipients whose teams failed to build.
    max_attempts: int = 6
    # Orgs handled per workflow execution. Each page runs in its own execution (chained via
    # continue_as_new) so history stays bounded no matter how many orgs are discovered.
    page_size: int = 1000
    # Continue-as-new carried state — never set by callers. cursor is the last org id of
    # the previous page (keyset paging: only this ~40-byte cursor rides between executions,
    # never the org list, so org count can't approach the 2 MiB payload cap); the carried_*
    # counters accumulate across the chain so the final execution can report and fail on
    # the whole run.
    cursor: str | None = None
    carried_orgs: int = 0
    carried_orgs_failed: int = 0
    carried_sent: int = 0


@dataclasses.dataclass(frozen=True)
class GetDigestOrgsInputs:
    org_ids: list[str] | None = None
    # Keyset page bounds: return at most ``limit`` org ids, sorted, strictly greater
    # than ``after``. The candidate set is recomputed each call; sorting makes paging
    # stable so an org can never be returned in two pages.
    after: str | None = None
    limit: int = 1000


@dataclasses.dataclass(frozen=True)
class SendOrgDigestInputs:
    org_id: str
    # Fail-safe default, matching WeeklyDigestInputs: the workflow always passes it explicitly.
    dry_run: bool = True
    # Must equal the activity's RetryPolicy.maximum_attempts — an activity cannot read its own
    # retry policy, and final-attempt detection (attempt >= max_attempts) depends on it.
    max_attempts: int = 6


@dataclasses.dataclass(frozen=True)
class SendOrgDigestResult:
    sent: int = 0
    teams_built: int = 0


@dataclasses.dataclass(frozen=True)
class WeeklyDigestResult:
    orgs: int
    orgs_failed: int
    sent: int
