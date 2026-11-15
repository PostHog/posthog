"""One row per job attempt with the commit and PR attribution of its run.

Jobs join runs on ``(ci_engine, run_id)`` and never on ``run_attempt``, because the runs snapshot
keeps only the newest attempt's row. A job whose run row is missing reads type defaults, not NULL.
"""

from typing import TYPE_CHECKING

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
)

from products.engineering_analytics.backend.logic.sources import resolve_job_source_tables
from products.engineering_analytics.backend.logic.views import workflow_jobs, workflow_runs

if TYPE_CHECKING:
    from posthog.models.team import Team

# Saved queries and insights select this view by name, so a rename breaks them.
VIEW_NAME = "engineering_analytics_ci_job_history"

# The column order is the UNION ALL order across sources and the saved-query schema, so append new
# columns and never reorder.
FIELDS: dict[str, FieldOrTable] = {
    "repo_owner": StringDatabaseField(name="repo_owner", nullable=True),
    "repo_name": StringDatabaseField(name="repo_name", nullable=True),
    "workflow_name": StringDatabaseField(name="workflow_name"),
    "job_name": StringDatabaseField(name="job_name"),
    "run_id": IntegerDatabaseField(name="run_id"),
    "run_attempt": IntegerDatabaseField(name="run_attempt"),
    "head_branch": StringDatabaseField(name="head_branch"),
    "head_sha": StringDatabaseField(name="head_sha", nullable=True),
    "status": StringDatabaseField(name="status"),
    "conclusion": StringDatabaseField(name="conclusion", nullable=True),
    "created_at": DateTimeDatabaseField(name="created_at", nullable=True),
    "created_at_raw": StringDatabaseField(name="created_at_raw", nullable=True),
    "started_at": DateTimeDatabaseField(name="started_at", nullable=True),
    "completed_at": DateTimeDatabaseField(name="completed_at", nullable=True),
    "duration_seconds": IntegerDatabaseField(name="duration_seconds", nullable=True),
    "pr_number": IntegerDatabaseField(name="pr_number", nullable=True),
    "commit_author_name": StringDatabaseField(name="commit_author_name", nullable=True),
    "commit_author_email": StringDatabaseField(name="commit_author_email", nullable=True),
    "commit_message": StringDatabaseField(name="commit_message", nullable=True),
    "commit_pr_number": IntegerDatabaseField(name="commit_pr_number", nullable=True),
    "is_merge_queue": BooleanDatabaseField(name="is_merge_queue"),
    # A copy carries the timestamps and conclusion of the attempt that ran, so a duration read that
    # counts it counts one execution twice.
    "is_rerun_copy": BooleanDatabaseField(name="is_rerun_copy"),
    "ci_engine": StringDatabaseField(name="ci_engine", nullable=True),
    "native_run_id": StringDatabaseField(name="native_run_id", nullable=True),
    "native_workflow_run_id": StringDatabaseField(name="native_workflow_run_id", nullable=True),
    "native_job_id": StringDatabaseField(name="native_job_id", nullable=True),
    "native_attempt_id": StringDatabaseField(name="native_attempt_id", nullable=True),
}


def _head_commit_query(runs_table: str) -> str:
    """The head commit's author and message per ``run_id``. A run with no commit object yields
    empty strings."""
    return f"""
        SELECT
            run_id,
            JSONExtractString(head_commit, 'author', 'name') AS commit_author_name,
            JSONExtractString(head_commit, 'author', 'email') AS commit_author_email,
            JSONExtractString(head_commit, 'message') AS commit_message
        FROM (
            SELECT
                id AS run_id,
                ifNull(head_commit, '{{}}') AS head_commit
            FROM {runs_table}
        )
    """


def build_query(
    *,
    jobs_table: workflow_jobs.JobsTable,
    runs_table: str,
    pull_requests_table: str | None = None,
    head_commit_runs_table: str | None = None,
) -> str:
    """The ``FIELDS`` columns for one source.

    Without ``pull_requests_table``, ``commit_pr_number`` comes only from the ``(#NNNN)`` suffix of
    the head commit's message. ``head_commit_runs_table`` names the plain GitHub runs table when
    ``runs_table`` also holds Depot CI runs, which carry no commit object.
    """
    jobs = workflow_jobs.build_query(jobs_table)
    runs = workflow_runs.build_query(runs_table, pull_requests_table=pull_requests_table)
    head_commits = _head_commit_query(head_commit_runs_table or runs_table)

    return f"""
        SELECT
            r.repo_owner AS repo_owner,
            r.repo_name AS repo_name,
            j.workflow_name AS workflow_name,
            j.name AS job_name,
            j.run_id AS run_id,
            j.run_attempt AS run_attempt,
            {workflow_jobs.branch("j", "r")} AS head_branch,
            r.head_sha AS head_sha,
            j.status AS status,
            j.conclusion AS conclusion,
            j.created_at AS created_at,
            j.created_at_raw AS created_at_raw,
            j.started_at AS started_at,
            j.completed_at AS completed_at,
            j.duration_seconds AS duration_seconds,
            -- The runs builder emits 0 for a run with no PR association; keep that semantic (a
            -- LEFT-JOIN miss also reads 0 — type default). commit_pr_number is the push-run fallback.
            r.pr_number AS pr_number,
            hc.commit_author_name AS commit_author_name,
            hc.commit_author_email AS commit_author_email,
            hc.commit_message AS commit_message,
            r.commit_pr_number AS commit_pr_number,
            -- The run ran on a merge-queue gate branch, so pr_number above is the PR it was landing
            -- rather than an association. Without this the two populations are indistinguishable.
            r.is_merge_queue AS is_merge_queue,
            j.is_rerun_copy AS is_rerun_copy,
            j.ci_engine AS ci_engine,
            j.native_run_id AS native_run_id,
            j.native_workflow_run_id AS native_workflow_run_id,
            j.native_job_id AS native_job_id,
            j.native_attempt_id AS native_attempt_id
        FROM ({jobs}) AS j
        LEFT JOIN ({runs}) AS r ON j.run_id = r.id AND j.ci_engine = r.ci_engine
        LEFT JOIN ({head_commits}) AS hc ON j.run_id = hc.run_id AND j.ci_engine = 'github_actions'
    """


def build_team_view(team: "Team") -> str | None:
    """The view body over every source with runs and jobs synced, or None when the team has none.

    The gate matches ``job_costs`` so that a team gets both views or neither.
    """
    sources = resolve_job_source_tables(team)
    if not sources:
        return None
    selects = [
        build_query(
            jobs_table=source.jobs_source,
            runs_table=source.runs_source,
            pull_requests_table=source.pull_requests,
            head_commit_runs_table=source.github_workflow_runs,
        )
        for source in sources
    ]
    return "\nUNION ALL\n".join(selects)
