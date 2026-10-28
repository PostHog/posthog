from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

TRUNK_IO_API_VERSION_V1 = "v1"
TRUNK_IO_API_VERSION_V2 = "v2"

BASE_URL = "https://api.trunk.io/v1"
# The v2 spec lists full `/v2/...` paths against the bare origin.
V2_BASE_URL = "https://api.trunk.io"

# The Merge Queue API is still served from v1: `/listPullRequests` paginates with top-level
# `cursor`/`take` body params, and it is scoped to one merge queue, i.e. one target branch.
MERGE_QUEUE_PAGE_SIZE = 100

MERGE_QUEUE_PULL_REQUESTS = "MergeQueuePullRequests"

# The flaky-test tables read `GET /v2/tests` across every test collection in the organization,
# because Trunk retires the repository-scoped v1 list endpoints once an org moves to collections.
# A v1 pin only hides the two tables that have no v1 name.
TEST_COLLECTIONS = "TestCollections"
TESTS = "Tests"

# `GET /v2/test-collections` and `GET /v2/tests` both take `limit` (max 100) and `cursor` query
# params and return `{data, nextCursor, hasMore}`.
V2_PAGE_SIZE = 100

TEST_METRICS_PARAMS: dict[str, str] = {"include": "metrics", "period": "7d"}

V1_ENDPOINTS = (
    "UnhealthyTests",
    "QuarantinedTests",
    "FailingTests",
    MERGE_QUEUE_PULL_REQUESTS,
)
V2_ENDPOINTS = (*V1_ENDPOINTS, TEST_COLLECTIONS, TESTS)

ENDPOINTS_BY_VERSION: dict[str, tuple[str, ...]] = {
    TRUNK_IO_API_VERSION_V1: V1_ENDPOINTS,
    TRUNK_IO_API_VERSION_V2: V2_ENDPOINTS,
}


def endpoints_for_version(api_version: str) -> tuple[str, ...]:
    try:
        return ENDPOINTS_BY_VERSION[api_version]
    except KeyError as e:
        raise ValueError(f"Unsupported Trunk.io API version: {api_version!r}") from e


DESCRIPTIONS: dict[str, str] = {
    "UnhealthyTests": "Tests Trunk currently considers flaky or broken, with their metrics over the last 7 days.",
    "QuarantinedTests": "Tests currently quarantined (failures suppressed), with their metrics over the last 7 days.",
    "FailingTests": "Tests that failed at least once in the last 7 days, most recent failure first.",
    MERGE_QUEUE_PULL_REQUESTS: "Pull requests submitted to the merge queue for one target branch, with queue state and priority.",
    TEST_COLLECTIONS: "Test collections in the organization, with test counts and quarantine settings.",
    TESTS: "Tests across every test collection in the organization, with current status and quarantine state.",
}

PRIMARY_KEYS: dict[str, list[str]] = {
    "UnhealthyTests": ["id"],
    "QuarantinedTests": ["id"],
    "FailingTests": ["id"],
    MERGE_QUEUE_PULL_REQUESTS: ["id"],
    TEST_COLLECTIONS: ["id"],
    TESTS: ["id"],
}

# `synced_through` is a synthetic per-row field (not part of any API response) carrying the point
# in time the row's endpoint is covered up to, so the pipeline's incremental watermark advances
# without depending on the order rows arrive in:
#
# - `FailingTests` has no server-side time filter, only a fixed 7-day metrics window, so every row
#   in a run is stamped with the run's start time and the merge on `id` keeps the latest metrics.
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
