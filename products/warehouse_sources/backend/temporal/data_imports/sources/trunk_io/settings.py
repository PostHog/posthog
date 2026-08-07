from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.trunk.io/v1"

# Trunk's list endpoints all paginate the same way: a `page_query: {page_size, page_token}`
# object nested in the POST body (not a top-level query/json param), capped at 100 rows/page.
PAGE_SIZE = 100

# `list-unhealthy-tests` requires a single `status` filter per call, so the "unhealthy tests"
# table is built by walking both statuses and merging the results.
UNHEALTHY_STATUSES = ("FLAKY", "BROKEN")

# `list-failing-tests` enforces a <=7 day start_time/end_time window per call, so a full sync
# walks forward in fixed windows. There is no per-row "modified since" field, so this default
# lookback bounds the first sync's backfill depth; later syncs continue from the last
# completed window (see `synced_through` below) instead of re-walking from this point again.
FAILING_TESTS_WINDOW_DAYS = 7
FAILING_TESTS_DEFAULT_LOOKBACK_DAYS = 30

# The Merge Queue API is a separate surface from Flaky Tests: `/listPullRequests` paginates with
# top-level `cursor`/`take` body params rather than the nested `page_query` object, and it is
# scoped to one merge queue, i.e. one target branch.
MERGE_QUEUE_PAGE_SIZE = 100

MERGE_QUEUE_PULL_REQUESTS = "MergeQueuePullRequests"

ENDPOINTS = (
    "UnhealthyTests",
    "QuarantinedTests",
    "FailingTests",
    MERGE_QUEUE_PULL_REQUESTS,
)

DESCRIPTIONS: dict[str, str] = {
    "UnhealthyTests": "Tests Trunk currently considers flaky or broken, combining both status filters.",
    "QuarantinedTests": "Tests currently quarantined (failures suppressed) in this repository.",
    "FailingTests": "Distinct tests that failed at least once within a given time window.",
    MERGE_QUEUE_PULL_REQUESTS: "Pull requests submitted to the merge queue for one target branch, with queue state and priority.",
}

PRIMARY_KEYS: dict[str, list[str]] = {
    "UnhealthyTests": ["id"],
    # Quarantined tests carry no stable id (`test_case_id` is explicitly documented as
    # unstable), so the natural key is the tuple that identifies the test case itself.
    "QuarantinedTests": ["name", "parent", "file", "classname", "variant"],
    "FailingTests": ["id"],
    MERGE_QUEUE_PULL_REQUESTS: ["id"],
}

# `synced_through` is a synthetic per-row field (not part of any API response) carrying the point
# in time the row's endpoint is covered up to, so the pipeline's incremental watermark advances
# without depending on the order rows arrive in:
#
# - `FailingTests` has a server-side `start_time`/`end_time` filter capped at 7 days, so each row
#   is stamped with the end of the window it was fetched in as the sync walks forward.
# - `MergeQueuePullRequests` has a server-side `since` filter on conclusion time but no documented
#   ordering, so every row in a run is stamped with the run's start time. The next run re-reads
#   from there, which overlaps by one run's duration rather than risking a gap; the overlap is
#   deduped by the merge on `id`.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "FailingTests": [incremental_field("synced_through", IncrementalFieldType.DateTime)],
    MERGE_QUEUE_PULL_REQUESTS: [incremental_field("synced_through", IncrementalFieldType.DateTime)],
}

# Merge Queue is a separate Trunk product from Flaky Tests and needs a target branch the other
# endpoints don't, so the table is offered but left unselected rather than failing every sync for
# the Flaky-Tests-only majority.
SHOULD_SYNC_DEFAULT: dict[str, bool] = {
    MERGE_QUEUE_PULL_REQUESTS: False,
}
