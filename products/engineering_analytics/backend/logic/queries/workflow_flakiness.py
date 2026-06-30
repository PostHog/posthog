"""Curated query: per-workflow flakiness over a window.

A ``(commit, workflow)`` is *flaky* when it failed at least once and then passed on a re-run
(``run_attempt > 1``) of the same head SHA. This counts, per workflow, how many distinct commits
flapped that way in the window — the read-layer definition of a flaky required check, defined once
here so the Signal emitter and any future surface share it (SPEC §7). Embedded as a subquery over
``curated.run_source()``; nothing is registered as a global HogQL view.
"""

from dataclasses import dataclass
from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

_SELECT = """
    WITH per_commit AS (
        SELECT
            repo_owner,
            repo_name,
            workflow_name,
            head_sha,
            countIf(conclusion IN ('failure', 'timed_out')) AS fails,
            countIf(conclusion = 'success' AND run_attempt > 1) AS rerun_passes
        FROM __RUNS_SOURCE__ AS r
        WHERE run_started_at >= {date_from} AND head_sha != ''
        GROUP BY repo_owner, repo_name, workflow_name, head_sha
    )
    SELECT
        repo_owner,
        repo_name,
        workflow_name,
        countIf(fails > 0 AND rerun_passes > 0) AS flaky_count,
        count() AS total_commits,
        arraySlice(groupArrayIf(head_sha, fails > 0 AND rerun_passes > 0), 1, 5) AS sample_head_shas
    FROM per_commit
    GROUP BY repo_owner, repo_name, workflow_name
    ORDER BY flaky_count DESC
    LIMIT 100
"""


@dataclass(frozen=True)
class WorkflowFlakiness:
    """Per-workflow flakiness over the window: how many distinct commits failed then passed on re-run."""

    repo_owner: str
    repo_name: str
    workflow_name: str
    flaky_count: int
    total_commits: int
    sample_head_shas: list[str]


def query_workflow_flakiness(*, curated: CuratedGitHubSource, date_from: datetime) -> list[WorkflowFlakiness]:
    sql = _SELECT.replace("__RUNS_SOURCE__", curated.run_source())
    response = curated.run(
        sql,
        query_type="engineering_analytics.workflow_flakiness",
        placeholders={"date_from": ast.Constant(value=date_from)},
    )
    return [
        WorkflowFlakiness(
            repo_owner=repo_owner,
            repo_name=repo_name,
            workflow_name=workflow_name,
            flaky_count=int(flaky_count),
            total_commits=int(total_commits),
            sample_head_shas=list(sample_head_shas or []),
        )
        for repo_owner, repo_name, workflow_name, flaky_count, total_commits, sample_head_shas in response.results or []
    ]
