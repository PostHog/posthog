from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions are taken verbatim from the Grafana Cloud k6 v6 OpenAPI spec
# (https://api.k6.io/cloud/v6/openapi). Keyed by the endpoint name from `get_schemas`.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "test_runs": {
        "description": "A single execution of a load test, including its status, result, and billable duration.",
        "docs_url": "https://grafana.com/docs/grafana-cloud/testing/k6/reference/cloud-rest-api/",
        "columns": {
            "id": "ID of the test run.",
            "test_id": "ID of the parent test.",
            "project_id": "ID of the parent project.",
            "started_by": "Email of the user who started the test if started with a user token.",
            "created": "Date and time when the test run was started.",
            "ended": "Date and time when the test run ended. Unset if the test is still running.",
            "note": "User-defined note for the test run.",
            "retention_expiry": "Timestamp after which the test run results are deleted.",
            "cost": "Test run cost details. The cost is available only after test run validation.",
            "status": "Current test run status.",
            "status_details": "Details of the current test run status.",
            "status_history": "List of test run status objects sorted by the status start time.",
            "distribution": "Load zones configured for the test and the corresponding distribution percentages.",
            "result": "Test run result: passed, failed, or error.",
            "options": "The original options object if available.",
            "max_vus": "The maximum number of total VUs (browser and protocol) at any stage of the execution plan.",
            "max_browser_vus": "The maximum number of browser VUs at any stage of the execution plan.",
            "estimated_duration": "The estimated duration of the test run in seconds.",
            "execution_duration": "The real billable duration of the test run in seconds.",
            "is_starred": "Whether the test run is starred for quick access.",
        },
    },
    "projects": {
        "description": "A project groups load tests, test runs, and members within a Grafana Cloud k6 stack.",
        "docs_url": "https://grafana.com/docs/grafana-cloud/testing/k6/reference/cloud-rest-api/",
        "columns": {
            "id": "Project ID.",
            "name": "Project name.",
            "is_default": "Whether this project is used as default when no explicit project ID is provided.",
            "grafana_folder_uid": "Grafana folder UID.",
            "created": "The date when the project was created.",
            "updated": "The date when the project was last updated.",
            "labels": "Project labels.",
        },
    },
    "load_tests": {
        "description": "A load test definition (script and configuration) that can be run to produce test runs.",
        "docs_url": "https://grafana.com/docs/grafana-cloud/testing/k6/reference/cloud-rest-api/",
        "columns": {
            "id": "ID of the load test.",
            "project_id": "ID of the parent project.",
            "name": "Unique name of the test within the project.",
            "baseline_test_run_id": "ID of a baseline test run used for results comparison.",
            "k6_version": "Identifier of the k6 version used to run the test.",
            "created": "The date when the test was created.",
            "updated": "The date when the test was last updated.",
        },
    },
    "schedules": {
        "description": "A schedule that triggers a load test to run once or on a recurring basis.",
        "docs_url": "https://grafana.com/docs/grafana-cloud/testing/k6/reference/cloud-rest-api/",
        "columns": {
            "id": "ID of the schedule.",
            "load_test_id": "ID of the test to run.",
            "starts": "The date on which the schedule will start running the test.",
            "recurrence_rule": "The schedule recurrence settings. Null if the test runs only once.",
            "cron": "The cron schedule to trigger the test periodically. Null if the test runs only once.",
            "deactivated": "Whether the schedule is deactivated.",
            "next_run": "The date of the next scheduled test run. Null if the schedule is expired.",
            "created_by": "The email of the user who created the schedule if applicable.",
        },
    },
    "load_zones": {
        "description": "A geographic load zone that test traffic can be generated from.",
        "docs_url": "https://grafana.com/docs/grafana-cloud/testing/k6/reference/cloud-rest-api/",
        "columns": {
            "id": "ID of the load zone.",
            "name": "Name of the load zone.",
            "k6_load_zone_id": "ID used to identify the load zone in the k6 scripts.",
            "available": "Whether the load zone can be used to start tests.",
            "custom_load_runner_image": "Custom load runner image. Only set for private load zones.",
            "public": "Whether the load zone is public or private.",
        },
    },
}
