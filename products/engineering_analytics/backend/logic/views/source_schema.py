"""Column types of the warehouse tables the builders read, as the sources land them.

The seed command and the warehouse tests build their tables from this file. Every column is Nullable,
timestamps are strings, and nested API objects are JSON strings. Keep new columns as nullable as the
source lands them, because a stricter type here hides a NULL-handling bug that only production data shows.
"""

PULL_REQUESTS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "number": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "title": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "state": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "draft": {"clickhouse": "Nullable(Bool)", "hogql": "BooleanDatabaseField"},
    "created_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "updated_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "merged_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "closed_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    # GitHub also fills this on an open PR, with a temporary test-merge SHA, so every read of it must
    # require the PR to be merged.
    "merge_commit_sha": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "user": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "head": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "base": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "labels": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

WORKFLOW_RUNS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "head_sha": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "head_branch": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "status": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "conclusion": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "created_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "run_started_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "updated_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "run_attempt": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "pull_requests": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "repository": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "head_commit": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    # The account GitHub recorded as triggering the run. Whoever pushed the branch cannot set it, so
    # logic/merge_queue.py checks it before it trusts a gate branch name.
    "actor": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    # GitHub's numeric id of the workflow, which stays the same when the workflow is renamed.
    "workflow_id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "event": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

# Runs columns that a synced table can lack, each with the typed NULL that ``views.depot_ci`` selects
# in its place. The Depot runs rows select the same NULLs, so both sides of the union agree on the types.
OPTIONAL_WORKFLOW_RUNS_COLUMNS: dict[str, str] = {
    "workflow_id": "toInt(NULL)",
    "event": "nullIf('', '')",
}

WORKFLOW_JOBS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "run_id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "run_attempt": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "workflow_name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "status": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "conclusion": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "head_sha": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "head_branch": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "labels": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "runner_name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "runner_group_name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "created_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "started_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "completed_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "steps": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

# One row per Depot CI job attempt. ``views.depot_ci`` reshapes these rows into the runs and jobs shapes above.
DEPOT_JOB_ATTEMPTS_COLUMNS: dict[str, dict[str, str]] = {
    **{
        name: {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"}
        for name in (
            "run_id",
            "repo",
            "ref",
            "head_sha",
            "sha",
            "workflow_id",
            "workflow_name",
            "workflow_status",
            "workflow_created_at",
            "workflow_started_at",
            "workflow_finished_at",
            "job_id",
            "job_key",
            "job_display_name",
            "attempt_id",
            "attempt_status",
            "attempt_started_at",
            "attempt_finished_at",
            "sandbox_id",
        )
    },
    "attempt": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "run_workflow_count": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
}

ISSUE_EVENTS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "event": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "actor": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "issue": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "created_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    # GitHub adds this object only to a team review request, so a repo where no pull request asked a team
    # lands no such column. The source resolver checks for it.
    "requested_team": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

# The source adds ``pr_number``, the number of the pull request each review belongs to.
REVIEWS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "pr_number": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "user": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "state": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "commit_id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "submitted_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

# The source adds the ``team_*`` columns to each member row. GitHub omits ``role`` from the documented
# member object, so a table can land without it and the source resolver checks for it (see
# ``MEMBER_ROLE_COLUMN`` in ``logic.sources``).
TEAM_MEMBERS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "login": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "role": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "team_id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "team_slug": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "team_name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

# One row per deploy request. The outcome is on the status rows below, so a read joins the two.
DEPLOYMENTS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "sha": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "ref": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "task": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "environment": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "original_environment": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "description": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "creator": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "payload": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "production_environment": {"clickhouse": "Nullable(Bool)", "hogql": "BooleanDatabaseField"},
    "transient_environment": {"clickhouse": "Nullable(Bool)", "hogql": "BooleanDatabaseField"},
    "created_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "updated_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

# One row per status transition of a deployment. The source adds ``deployment_id``.
DEPLOYMENT_STATUSES_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "deployment_id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "state": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "creator": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "description": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "environment": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "target_url": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "log_url": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "environment_url": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "created_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "updated_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

# One row per Trunk merge-queue entry, with the state it last reached. Trunk keeps no state history,
# so ``state_changed_at`` is the time of the last transition only.
TRUNK_MERGE_QUEUE_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "state": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "pr_number": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "priority_name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "skip_the_line": {"clickhouse": "Nullable(Bool)", "hogql": "BooleanDatabaseField"},
    "state_changed_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

# The quarantined-tests table of a Trunk source that last synced on the v1 API. Trunk documents
# ``test_case_id`` as unstable.
TRUNK_QUARANTINED_TESTS_V1_COLUMNS: dict[str, dict[str, str]] = {
    "file": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "labels": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "parent": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "status": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "variant": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "classname": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "codeowners": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "test_case_id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "quarantined_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "quarantine_setting": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "status_last_updated_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

# The quarantined-tests table on the v2 API: one row per quarantined test across every test collection.
TRUNK_QUARANTINED_TESTS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "test_collection_id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "file": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "labels": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "parent_name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "class_name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "variant": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "status": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "codeowners": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "quarantine_state": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "quarantined_since": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "url": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}
