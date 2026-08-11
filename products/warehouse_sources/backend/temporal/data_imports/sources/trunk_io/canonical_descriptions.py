from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.settings import MERGE_QUEUE_PULL_REQUESTS

_FLAKY_TESTS_DOCS_URL = "https://docs.trunk.io/flaky-tests/api"
_MERGE_QUEUE_DOCS_URL = "https://docs.trunk.io/merge-queue/reference/merge"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "UnhealthyTests": {
        "description": "Tests Trunk currently considers flaky or broken, combining the `FLAKY` and `BROKEN` status filters.",
        "docs_url": _FLAKY_TESTS_DOCS_URL,
        "columns": {
            "id": "A stable unique identifier for the test.",
            "repository": "The repository the test belongs to.",
            "html_url": "The URL of the test details page in the Trunk app.",
            "name": "The name of the test.",
            "variant": "The name of the test variant.",
            "status": "The test's current status: value (healthy/flaky/broken), reason, and the timestamp of the last status change.",
            "file_path": "The file path of the test.",
            "parent": "The parent of the test, including the test suite depending on the test runner.",
            "classname": "The class name of the test.",
            "codeowners": "Code owners for the test.",
            "pull_requests_impacted_last_7d": "The number of pull requests impacted by this test in the last 7 days.",
            "quarantined": "Whether the test is currently quarantined.",
            "ticket": "The ticket linked to this test case, if any.",
        },
    },
    "QuarantinedTests": {
        "description": "Tests currently quarantined (failures suppressed so CI still passes) in this repository.",
        "docs_url": _FLAKY_TESTS_DOCS_URL,
        "columns": {
            "name": "The name of the test case.",
            "parent": "The parent of the test case.",
            "file": "The file of the test case.",
            "classname": "The class name of the test case.",
            "status": "The status of the test case (HEALTHY/FLAKY/BROKEN).",
            "codeowners": "The latest code owners of the test case.",
            "quarantine_setting": "Why the test is quarantined (ALWAYS_QUARANTINE or AUTO_QUARANTINE).",
            "quarantined_at": "The time the test case was quarantined.",
            "status_last_updated_at": "The last time the test case's status was updated.",
            "test_case_id": "An identifier for the test case. Not guaranteed to be stable over time.",
            "variant": "The variant of the test case.",
        },
    },
    "FailingTests": {
        "description": "Distinct tests that failed at least once within a given time window.",
        "docs_url": _FLAKY_TESTS_DOCS_URL,
        "columns": {
            "id": "A stable unique identifier for the test.",
            "repository": "The repository the test belongs to.",
            "html_url": "The URL of the test details page in the Trunk app.",
            "name": "The name of the test.",
            "variant": "The name of the test variant.",
            "status": "The test's current status: value (healthy/flaky/broken), reason, and the timestamp of the last status change.",
            "most_common_failures": "The most common failure summaries for this test, with occurrence counts.",
            "failure_rate_last_7d": "The failure rate over the last 7 days.",
            "failure_rate_last_24h": "The failure rate over the last 24 hours.",
            "file_path": "The file path of the test.",
            "parent": "The parent of the test, including the test suite depending on the test runner.",
            "classname": "The class name of the test.",
            "codeowners": "Code owners for the test.",
            "pull_requests_impacted_last_7d": "The number of pull requests impacted by this test in the last 7 days.",
            "quarantined": "Whether the test is currently quarantined.",
            "ticket": "The ticket linked to this test case, if any.",
            "synced_through": "PostHog-added: the end of the time window this row was synced in, used to track incremental progress.",
        },
    },
    MERGE_QUEUE_PULL_REQUESTS: {
        "description": "Pull requests submitted to the repository's merge queue for one target branch, with the state each one reached and how it was prioritized.",
        "docs_url": _MERGE_QUEUE_DOCS_URL,
        "columns": {
            "id": "A unique identifier for this pull request's entry in the merge queue.",
            "state": "The pull request's state in the queue: not_ready, pending, testing, tests_passed, merged, failed, cancelled or pending_failure.",
            "stateChangedAt": "The time the pull request last changed state.",
            "priorityValue": "The numeric priority the pull request was queued at.",
            "priorityName": "The name of the priority the pull request was queued at.",
            "usedDefaultPriorityName": "The default priority name applied when the pull request did not set one.",
            "skipTheLine": "Whether the pull request jumped ahead of the rest of the queue.",
            "noBatch": "Whether the pull request was tested on its own rather than batched with others.",
            "prNumber": "The pull request number in the source control provider.",
            "prTitle": "The title of the pull request.",
            "prSha": "The commit SHA of the pull request.",
            "prBaseBranch": "The base branch of the pull request.",
            "prAuthor": "The author of the pull request.",
            "synced_through": "PostHog-added: the start of the sync run this row was fetched in, used to track incremental progress.",
        },
    },
}
