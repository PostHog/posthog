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

ENDPOINTS = (
    "UnhealthyTests",
    "QuarantinedTests",
    "FailingTests",
)

DESCRIPTIONS: dict[str, str] = {
    "UnhealthyTests": "Tests Trunk currently considers flaky or broken, combining both status filters.",
    "QuarantinedTests": "Tests currently quarantined (failures suppressed) in this repository.",
    "FailingTests": "Distinct tests that failed at least once within a given time window.",
}

PRIMARY_KEYS: dict[str, list[str]] = {
    "UnhealthyTests": ["id"],
    # Quarantined tests carry no stable id (`test_case_id` is explicitly documented as
    # unstable), so the natural key is the tuple that identifies the test case itself.
    "QuarantinedTests": ["name", "parent", "file", "classname", "variant"],
    "FailingTests": ["id"],
}

# `FailingTests` is the only endpoint with a real server-side time filter (start_time/end_time).
# `synced_through` is a synthetic per-row field (not part of the API response) stamped with the
# end of the window each row was fetched in, so the pipeline's incremental watermark advances as
# we walk forward through time.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "FailingTests": [incremental_field("synced_through", IncrementalFieldType.DateTime)],
}
