from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "test_runs": {
        "description": "Automated test runs with their status, timing, test statistics, and Git metadata.",
        "docs_url": "https://docs.testdino.com/api-reference/endpoints/test-runs/list-test-runs",
        "columns": {
            "id": "Unique identifier of the test run.",
            "counter": "Run counter number.",
            "status": "Run status: passed, failed, interrupted, incomplete, or running.",
            "startTime": "Time when the run started.",
            "endTime": "Time when the run ended.",
            "testStats": "Counts of test outcomes for the run.",
            "metadata": "Run metadata, including Git details.",
            "url": "Link to the run in TestDino.",
        },
    },
    "manual_suites": {
        "description": "Manual test suites with their hierarchy and modification details.",
        "docs_url": "https://docs.testdino.com/api-reference/endpoints/manual-tests/list-manual-suites",
        "columns": {
            "_id": "Unique identifier of the suite.",
            "name": "Suite name.",
            "hierarchy": "Parent suite, display order, and nesting depth.",
            "childSuitesCount": "Number of direct child suites.",
            "children": "Nested child suites.",
            "updatedAt": "Time of the last suite update.",
        },
    },
    "manual_cases": {
        "description": "Manual test cases with their classification, automation status, steps, and suite details.",
        "docs_url": "https://docs.testdino.com/api-reference/endpoints/manual-tests/list-manual-test-cases",
        "columns": {
            "_id": "Unique identifier of the test case.",
            "caseId": "Display identifier of the test case.",
            "title": "Test case title.",
            "classification": "Test classification, including priority and severity.",
            "automation": "Automation details for the test case.",
            "steps": "Test case steps.",
            "customFields": "Values of custom fields defined in the project.",
            "createdAt": "Time when the test case was created.",
            "updatedAt": "Time of the last test case update.",
        },
    },
}
