"""Curated workflow-runs query builder.

Maps the raw GitHub workflow-runs warehouse snapshot into honest CI columns:
``status`` and ``conclusion`` are passed through unchanged (a conclusion can be
stale until the ``workflow_run`` webhook settles it — see SPEC §9), and
``duration_seconds`` is only computed for completed runs. ``head_sha`` is the
canonical join key back to the pull-requests builder for a PR's CI status, while
``pr_number`` keys the per-PR push / re-run rollup and ``run_attempt`` distinguishes
re-runs. The source table name is resolved per-team and passed in (see
``logic.sources``); it is never hardcoded, because a warehouse table's name carries
the user-chosen source prefix.

``pr_number`` is the FIRST entry of the run's ``pull_requests`` association. Two cases:
a run with no association (fork PRs, and pushes to a branch with no open PR) extracts
``0`` (filtered out of the rollup, which only counts ``pr_number > 0``); a run shared
across more than one PR (uncommon — one head tied to multiple open PRs) is credited to
its first PR only, not fanned out across all of them. That's a deliberate v1
simplification — the rollup is an approximate friction signal (pushes / re-runs), not
billing — kept until the job-level source (SPEC §6) replaces this attribution.

The real GitHub source lands timestamps as **strings** and ``repository`` /
``pull_requests`` as **Nullable** JSON, so this builder runs in two layers: an inner
SELECT parses each timestamp with ``parseDateTimeBestEffort`` and unwraps the
Nullable JSON with ``ifNull`` (a Nullable column cannot feed ``JSONExtractArrayRaw`` /
``splitByChar`` — ClickHouse rejects an Array nested inside a Nullable); the outer
SELECT derives the duration and repo identity off those parsed columns, which also
avoids referencing a same-SELECT alias as another expression's input.

Every query module embeds this ``SELECT`` as a subquery (see ``_curated``);
nothing registers it as a global HogQL view.
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
