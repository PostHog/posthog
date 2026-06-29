"""Curated workflow-runs query builder.

Maps the raw GitHub workflow-runs snapshot into honest CI columns: ``status`` and ``conclusion`` pass
through (a conclusion can be stale until the ``workflow_run`` webhook settles it — SPEC §9), and
``duration_seconds`` is only computed for completed runs. ``head_sha`` is the join key back to the
pull-requests builder; ``pr_number`` keys the per-PR push / re-run rollup; ``run_attempt`` distinguishes
re-runs. The source table name is resolved per-team and passed in; never hardcoded.

``pr_number`` is the FIRST entry of the run's ``pull_requests`` association. No association (fork PRs,
pushes to a branch with no open PR) extracts ``0`` (filtered out of the rollup); a run shared across
multiple PRs is credited to its first only. A deliberate v1 simplification — the rollup is an
approximate friction signal, not billing — kept until the job-level source (SPEC §6) replaces it.

Two-layer like the PR builder: the inner SELECT parses timestamps with ``parseDateTimeBestEffort`` and
unwraps Nullable JSON with ``ifNull`` (ClickHouse rejects an Array nested inside a Nullable); the outer
derives duration and repo identity, also avoiding referencing a same-SELECT alias.
"""


def build_query(table_name: str) -> str:
    return f"""
        SELECT
            id,
            workflow_name,
            head_sha,
            head_branch,
            status,
            conclusion,
            run_started_at,
            updated_at,
            created_at,
            run_attempt,
            pr_number,
            if(status = 'completed', dateDiff('second', run_started_at, updated_at), NULL) AS duration_seconds,
            arrayElement(repo_parts, 1) AS repo_owner,
            arrayElement(repo_parts, 2) AS repo_name
        FROM (
            SELECT
                id,
                name AS workflow_name,
                head_sha,
                head_branch,
                status,
                conclusion,
                run_attempt,
                JSONExtractInt(arrayElement(JSONExtractArrayRaw(ifNull(pull_requests, '[]')), 1), 'number') AS pr_number,
                splitByChar('/', ifNull(JSONExtractString(repository, 'full_name'), '')) AS repo_parts,
                parseDateTimeBestEffort(run_started_at) AS run_started_at,
                parseDateTimeBestEffort(updated_at) AS updated_at,
                parseDateTimeBestEffort(created_at) AS created_at
            FROM {table_name}
        )
    """
