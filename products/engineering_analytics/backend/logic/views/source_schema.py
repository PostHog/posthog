"""Column schemas of the raw GitHub warehouse snapshots the curated views read.

These mirror what the GitHub warehouse source actually lands: scalar columns plus
the nested API objects (``user``, ``head``, ``base``, ``labels``, ``repository``,
``pull_requests``) stored verbatim as JSON strings, and timestamps as strings.

**Every column is ``Nullable`` — the data-imports pipeline lands the whole GitHub
snapshot as nullable, with no exceptions** (verified against the real connected
source). The curated builders therefore parse timestamps with
``parseDateTimeBestEffort`` (NULL-safe) and ``ifNull``-unwrap any Nullable column
before an array function (``JSONExtractArrayRaw`` / ``splitByChar``), because
ClickHouse rejects an Array nested inside a Nullable.

This file is the single source of truth for the table shape, shared by the seed
command and the warehouse tests. It must stay a faithful replica of prod: the
original idealized shape (non-null scalars, ``DateTime64`` timestamps) passed every
local test while production 500'd on the real nullable table. Keeping it exactly as
nullable as prod is what makes the warehouse tests catch a Nullable-handling
regression locally / in CI instead of only after deploy. If you add a column here,
type it ``Nullable(...)`` unless you have confirmed the pipeline lands it non-null.
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
    # The commit the merge produced on the base branch: the key that resolves a default-branch push
    # run back to the PR that landed it. GitHub also populates it on OPEN PRs, where it is a
    # throwaway test-merge SHA, so every read of it must gate on the PR being merged.
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
    # The run's head commit object (author, message, id) verbatim as JSON. Carries the commit
    # attribution the ci_job_history view extracts; a push run's PR number rides its squash-merge
    # message when the pull_requests association is empty (master pushes). Nullable like every column.
    "head_commit": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    # The account GitHub recorded as triggering the run, verbatim as JSON. GitHub sets it; whoever
    # pushed the branch cannot, which is what makes it the corroboration a merge-queue gate branch
    # is checked against before its name is trusted for attribution (see logic/merge_queue.py).
    "actor": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

# Contract for the incoming ``github_workflow_jobs`` warehouse source (job-level CI: queue
# time, per-job duration, runner tier, retries) — the substrate per-PR Depot cost wires to.
# The source must land exactly this shape; ``run_id`` joins back to ``github_workflow_runs``
# for per-PR attribution, ``labels`` carries the runner tier the cost model parses. Same
# Nullable/string discipline as above — timestamps are strings, ``labels``/``steps`` are JSON.
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

# Contract for the ``github_issue_events`` warehouse source: immutable issue/PR events, every
# type kept (a source-side filter would pin the desc-walk watermark). ``actor`` / ``issue`` are
# the nested GitHub objects verbatim as JSON. Same Nullable/string discipline as above.
ISSUE_EVENTS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "event": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "actor": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "issue": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "created_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

# Contract for the ``github_team_members`` warehouse source (org team membership). Member rows
# are GitHub user objects with the parent team's identity injected by the source fan-out
# (``team_id`` / ``team_slug`` / ``team_name``); ``login`` + ``team_slug`` are the join keys the
# membership-based merge timing reads. Same Nullable discipline as above.
TEAM_MEMBERS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "login": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "team_id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "team_slug": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "team_name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

# Contract for the ``github_deployments`` warehouse source: one row per deploy request (a SHA
# aimed at an environment), webhook-fed. The outcome lives on the status children below, so the
# DORA reads always join the two. Same Nullable/string discipline as above.
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

# Contract for the ``github_deployment_statuses`` warehouse source: one row per status transition
# of a deployment (pending / in_progress / queued / success / failure / error / inactive), with the
# parent's id injected by the source fan-out. Append-oriented — the transition history is what the
# DORA change-failure and restore proxies read. Same Nullable/string discipline as above.
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

# The Trunk merge-queue snapshot (TrunkIo source, opt-in MergeQueuePullRequests endpoint): one row
# per queue entry with the state it last reached. Trunk keeps no state history, so
# ``state_changed_at`` is the entry's last transition, not a timeline. Typed by the trunk_io
# pipeline (verified against a real connected source); Nullable like everything else it lands.
TRUNK_MERGE_QUEUE_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "state": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "pr_number": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "priority_name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "skip_the_line": {"clickhouse": "Nullable(Bool)", "hogql": "BooleanDatabaseField"},
    "state_changed_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

# The Trunk quarantined-tests snapshot (TrunkIo source, QuarantinedTests endpoint): one row per
# currently quarantined test case, keyed by the (name, parent, file, classname, variant) tuple
# because Trunk documents ``test_case_id`` as unstable. Verified against a real connected source;
# every column lands Nullable(String), timestamps included.
TRUNK_QUARANTINED_TESTS_COLUMNS: dict[str, dict[str, str]] = {
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
