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
    # How many per-org activities run at once within each page. Every page runs at once, so
    # this is the only cap on the run's ClickHouse demand: peak concurrency is this value
    # times ceil(total_orgs / page_size). The offline cluster has a global concurrent-query
    # limit shared with every other product, so the value has to leave room for them.
    max_concurrent: int = 5
    # Total executions per org activity: initial run + 7 retries. The final attempt sends
    # partial digests instead of deferring recipients whose teams failed to build.
    # See SEND_ORG_* in workflow.py for the retry pacing this count is chosen against.
    max_attempts: int = 8
    # Orgs handled per page child workflow. Bounds each page's history and the size of
    # the org-id slice its load activity returns (~40KB per 1000 orgs).
    page_size: int = 1000


@dataclasses.dataclass(frozen=True)
class GetDigestOrgsInputs:
    # Object storage key the discovered org ids are written to. Discovery returns only this
    # key and a count, keeping the discovered org list out of workflow history no matter how
    # many orgs it finds. A targeted manual run still passes its org_ids through directly.
    storage_key: str
    org_ids: list[str] | None = None


@dataclasses.dataclass(frozen=True)
class GetDigestOrgsResult:
    total_orgs: int


@dataclasses.dataclass(frozen=True)
class CleanupDigestOrgsInputs:
    storage_key: str


@dataclasses.dataclass(frozen=True)
class LoadPageOrgsInputs:
    storage_key: str
    # 1-based page number into the stored sorted org list; the activity returns the
    # [page_size * (page_number - 1), page_size * page_number) slice.
    page_number: int
    page_size: int


@dataclasses.dataclass(frozen=True)
class WeeklyDigestPageInputs:
    storage_key: str
    page_number: int
    page_size: int
    dry_run: bool = True
    max_concurrent: int = 5
    max_attempts: int = 8


@dataclasses.dataclass(frozen=True)
class SendOrgDigestInputs:
    org_id: str
    # Fail-safe default, matching WeeklyDigestInputs: the workflow always passes it explicitly.
    dry_run: bool = True
    # Must equal the activity's RetryPolicy.maximum_attempts, because an activity cannot read
    # its own retry policy and final-attempt detection (attempt >= max_attempts) depends on it.
    max_attempts: int = 8


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
