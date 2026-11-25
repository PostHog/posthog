from products.warehouse_sources.sources.sdk import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workflows": {
        "description": "Workflow runs for the selected Semaphore project.",
        "docs_url": "https://docs.semaphore.io/reference/api#list-workflows",
        "columns": {
            "wf_id": "Unique workflow identifier.",
            "project_id": "Project that owns the workflow.",
            "created_at": "Workflow creation time in UTC.",
            "initial_ppl_id": "Identifier of the first pipeline.",
            "commit_sha": "Git commit for the workflow.",
            "branch_name": "Git branch for the workflow.",
        },
    },
    "pipelines": {
        "description": "Pipelines and their execution states for the selected project.",
        "docs_url": "https://docs.semaphore.io/reference/api#list-pipelines",
        "columns": {
            "ppl_id": "Unique pipeline identifier.",
            "wf_id": "Workflow that contains the pipeline.",
            "state": "Pipeline execution state.",
            "result": "Pipeline result after execution ends.",
            "created_at": "Pipeline creation time in UTC.",
        },
    },
    "deployment_targets": {
        "description": "Deployment targets configured for the selected project.",
        "docs_url": "https://docs.semaphore.io/reference/api#list-targets",
        "columns": {
            "id": "Unique deployment target identifier.",
            "project_id": "Project that owns the target.",
            "name": "Deployment target name.",
            "created_at": "Target creation time in UTC.",
        },
    },
    "members": {
        "description": "Human users who are members of the Semaphore organization, with their roles.",
        "docs_url": "https://docs.semaphore.io/reference/api#list-members",
        "columns": {
            "id": "Unique identifier of the member.",
            "subject_type": "Kind of member, such as user.",
            "name": "Display name of the member.",
            "roles": "Roles assigned to the member and how each role was granted.",
        },
    },
    "deployment_history": {
        "description": "Deployments triggered on each deployment target of the selected project.",
        "docs_url": "https://docs.semaphore.io/reference/api#retrieve-deployment-history",
        "columns": {
            "id": "Unique deployment identifier.",
            "target_id": "Deployment target that received the deployment.",
            "target_name": "Name of the deployment target.",
            "triggered_by": "User ID or system event that triggered the deployment.",
            "triggered_at": "Time when the deployment was triggered, in UTC.",
            "state": "Deployment state.",
            "pipeline_id": "Pipeline that the deployment started.",
            "prev_pipeline_id": "Pipeline that was promoted to start the deployment.",
            "env_vars": "Parameters passed to the deployment.",
        },
    },
    "flaky_tests": {
        "description": "Tests that Semaphore detected as flaky in the selected project.",
        "docs_url": "https://docs.semaphore.io/reference/api#list-flaky-tests",
        "columns": {
            "id": "Unique identifier of the flaky test record.",
            "test_name": "Name of the test.",
            "group": "Test group or class.",
            "file": "Source file of the test.",
            "suite": "Test suite name.",
            "pass_rate": "Percentage of runs where the test passed.",
            "disruptions": "Number of pipeline runs that the test disrupted.",
            "resolved": "Whether the flaky test is marked as resolved.",
            "first_seen": "Date of the first flaky occurrence.",
            "last_seen": "Date of the most recent flaky occurrence.",
        },
    },
    "flaky_test_disruptions": {
        "description": "Pipeline runs that each flaky test disrupted in the selected project.",
        "docs_url": "https://docs.semaphore.io/reference/api#list-disruptions-for-a-flaky-test",
        "columns": {
            "flaky_test_id": "Flaky test that disrupted the pipeline run.",
            "pipeline_id": "Disrupted pipeline.",
            "workflow_id": "Workflow that contains the disrupted pipeline.",
            "branch": "Git branch of the disrupted run.",
            "commit_sha": "Git commit of the disrupted run.",
            "created_at": "Time of the disruption in UTC.",
        },
    },
}
