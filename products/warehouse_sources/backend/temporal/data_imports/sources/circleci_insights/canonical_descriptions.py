from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workflow_metrics": {
        "description": "Aggregated metrics for each workflow in a project over the configured reporting window: run counts, success rate, duration percentiles, credits consumed, MTTR, and throughput.",
        "docs_url": "https://circleci.com/docs/api/v2/index.html#operation/getProjectWorkflowMetrics",
        "columns": {
            "name": "The name of the workflow.",
            "metrics": "Metrics aggregated over the reporting window: total/successful/failed runs, success rate, duration percentiles (min, mean, median, p95, max), total credits used, MTTR, and throughput.",
            "window_start": "The start of the aggregation window for the workflow's metrics.",
            "window_end": "The end of the aggregation window for the workflow's metrics.",
            "project_id": "The unique ID of the project the workflow belongs to.",
            "project_slug": "The project slug (vcs/org/repo) the workflow belongs to, as configured on the source.",
        },
    },
    "workflow_runs": {
        "description": "Individual recent runs of each workflow, with duration, status, branch, and credits consumed. CircleCI retains run-level Insights data for roughly 90 days.",
        "docs_url": "https://circleci.com/docs/api/v2/index.html#operation/getProjectWorkflowRuns",
        "columns": {
            "id": "The unique ID of the workflow run.",
            "branch": "The VCS branch the run was triggered on.",
            "duration": "The duration of the run, in seconds.",
            "status": "The outcome of the run (e.g. success, failed, canceled).",
            "created_at": "The date and time the run was created.",
            "stopped_at": "The date and time the run stopped.",
            "credits_used": "The number of credits the run consumed.",
            "is_approval": "Whether the run is an approval workflow.",
            "workflow_name": "The name of the workflow the run belongs to.",
            "project_slug": "The project slug (vcs/org/repo) the run belongs to, as configured on the source.",
        },
    },
    "job_metrics": {
        "description": "Aggregated metrics for each job of each workflow in a project over the configured reporting window: run counts, success rate, duration percentiles, credits consumed, and throughput.",
        "docs_url": "https://circleci.com/docs/api/v2/index.html#operation/getWorkflowJobMetrics",
        "columns": {
            "name": "The name of the job.",
            "metrics": "Metrics aggregated over the reporting window: total/successful/failed runs, success rate, duration percentiles (min, mean, median, p95, max), total credits used, and throughput.",
            "window_start": "The start of the aggregation window for the job's metrics.",
            "window_end": "The end of the aggregation window for the job's metrics.",
            "workflow_name": "The name of the workflow the job belongs to.",
            "project_slug": "The project slug (vcs/org/repo) the job belongs to, as configured on the source.",
        },
    },
    "flaky_tests": {
        "description": "Tests CircleCI has detected as flaky in a project: tests that pass and fail across runs with no code change, with where they flake and how often.",
        "docs_url": "https://circleci.com/docs/api/v2/index.html#operation/getFlakyTests",
        "columns": {
            "test_name": "The name of the flaky test.",
            "classname": "The class or suite the flaky test belongs to.",
            "file": "The source file of the flaky test, when reported.",
            "job_name": "The name of the job the test most recently flaked in.",
            "job_number": "The number of the job the test most recently flaked in.",
            "workflow_name": "The name of the workflow the test most recently flaked in.",
            "workflow_id": "The ID of the workflow run the test most recently flaked in.",
            "workflow_created_at": "The date and time of the workflow run the test most recently flaked in.",
            "pipeline_number": "The number of the pipeline the test most recently flaked in.",
            "times_flaked": "How many times the test has flaked.",
            "time_wasted": "The time wasted on the test's flakiness, in seconds.",
            "source": "The source of the flaky-test detection.",
            "project_slug": "The project slug (vcs/org/repo) the flaky test belongs to, as configured on the source.",
        },
    },
    "org_summary_metrics": {
        "description": "Per-project summary metrics and trends across an organization over the configured reporting window, from the org-level Insights summary. Requires the token to have org membership.",
        "docs_url": "https://circleci.com/docs/api/v2/index.html#operation/getOrgSummaryData",
        "columns": {
            "project_name": "The name of the project the metrics belong to.",
            "metrics": "Summary metrics for the project over the reporting window (throughput, duration, success rate, credits).",
            "trends": "Trends for the project's metrics relative to the previous window.",
            "org_slug": "The organization slug (vcs/org) derived from the configured project slugs.",
        },
    },
}
