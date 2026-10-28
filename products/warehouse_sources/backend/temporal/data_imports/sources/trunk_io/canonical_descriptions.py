from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.settings import (
    MERGE_QUEUE_PULL_REQUESTS,
    TEST_COLLECTIONS,
    TESTS,
)

_MERGE_QUEUE_DOCS_URL = "https://docs.trunk.io/merge-queue/reference/merge"
_V2_DOCS_URL = "https://docs.trunk.io/flaky-tests/reference/api-reference"

_TEST_COLUMNS: dict[str, str] = {
    "id": "A stable unique identifier for the test.",
    "testCollectionId": "The id of the collection that owns the test.",
    "repositoryId": "The id of the repository the test was uploaded for. Uploads made without a repository carry the nil UUID.",
    "name": "The name of the test.",
    "parentName": "The parent of the test, such as its test suite.",
    "className": "The class name of the test.",
    "file": "The file path of the test.",
    "target": "The build target that ran the test, when one was reported.",
    "variant": "The variant of the test.",
    "crossVariantId": "Groups the same test across variants, when it has any.",
    "codeowners": "Code owners for the test.",
    "status": "The test's current status: healthy, flaky or broken.",
    "statusSince": "When the status last changed. Empty for a test no monitor has classified yet.",
    "quarantineState": "Whether the test is currently quarantined: quarantined or notQuarantined.",
    "quarantinedSince": "When the test's current quarantine began. Empty when the test is not quarantined.",
    "labels": "The labels on the test, with what applied each one.",
    "url": "The test's page in the Trunk app.",
    "ticket": "The ticket linked to this test, if any.",
}

_TEST_METRICS_COLUMNS: dict[str, str] = {
    **_TEST_COLUMNS,
    "metrics": "The test's failure rate, pull requests impacted, run and failure counts, p95 duration, last run and last failure over the last 7 days. Empty when the test had no runs.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "UnhealthyTests": {
        "description": "Tests Trunk currently considers flaky or broken, across every test collection, with their metrics over the last 7 days.",
        "docs_url": _V2_DOCS_URL,
        "columns": _TEST_METRICS_COLUMNS,
    },
    "QuarantinedTests": {
        "description": "Tests currently quarantined (failures suppressed so CI still passes), across every test collection, with their metrics over the last 7 days.",
        "docs_url": _V2_DOCS_URL,
        "columns": _TEST_METRICS_COLUMNS,
    },
    "FailingTests": {
        "description": "Tests that failed at least once in the last 7 days, across every test collection, most recent failure first.",
        "docs_url": _V2_DOCS_URL,
        "columns": {
            **_TEST_METRICS_COLUMNS,
            "synced_through": "PostHog-added: the start of the sync run this row was fetched in, used to track incremental progress.",
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
    TEST_COLLECTIONS: {
        "description": "Test collections in the organization. Each collection has its own flake detection, quarantining and ticketing settings.",
        "docs_url": _V2_DOCS_URL,
        "columns": {
            "id": "The collection's id.",
            "name": "The name of the collection.",
            "description": "The description of the collection, if any.",
            "testCount": "The number of distinct tests seen in this collection. Stays 0 until the first upload is processed.",
            "quarantineEnabled": "Whether quarantining is turned on for this collection.",
            "autoQuarantineEnabled": "Whether flaky tests in this collection are quarantined automatically.",
            "createdAt": "The time the collection was created.",
            "updatedAt": "The time the collection was last updated.",
        },
    },
    TESTS: {
        "description": "Tests across every test collection in the organization, with their current status and quarantine state.",
        "docs_url": _V2_DOCS_URL,
        "columns": _TEST_COLUMNS,
    },
}
