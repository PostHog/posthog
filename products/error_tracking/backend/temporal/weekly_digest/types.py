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
    # Orgs handled per page. Per-org activity history lives in the page child workflows;
    # the parent still records ~80KB per page (discovery result + child input), so it
    # holds to roughly 600k orgs before nearing Temporal's 50MB history cap.
    page_size: int = 1000
    # Pages processed concurrently as child workflows. The global org-activity target is
    # max_concurrent_pages * max_concurrent — keep it at or below the worker fleet's
    # activity-slot capacity (35 in prod) or the extra pages just queue.
    max_concurrent_pages: int = 3


@dataclasses.dataclass(frozen=True)
class GetDigestOrgsInputs:
    org_ids: list[str] | None = None
    # Keyset page bounds: return at most ``limit`` org ids, sorted, strictly greater
    # than ``after``. The candidate set is recomputed each call; sorting makes paging
    # stable so an org can never be returned in two pages.
    after: str | None = None
    limit: int = 1000


@dataclasses.dataclass(frozen=True)
class WeeklyDigestPageInputs:
    # ~40 bytes per org id: a 1000-org page rides well under the 2 MiB payload cap.
    org_ids: list[str]
    dry_run: bool = True
    max_concurrent: int = 10
    max_attempts: int = 6


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
    # Across every attempt, not just the one that returned this result: Temporal surfaces only the
    # final attempt's return value.
    sent: int = 0
    teams_built: int = 0


@dataclasses.dataclass(frozen=True)
class WeeklyDigestResult:
    orgs: int
    orgs_failed: int
    sent: int
