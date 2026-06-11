"""Curated ``github_workflow_runs`` query builder.

Maps the raw ``github_workflow_runs`` warehouse snapshot into honest CI columns:
``status`` and ``conclusion`` are passed through unchanged (a conclusion can be
stale until the ``workflow_run`` webhook settles it — see SPEC §9), and
``duration_seconds`` is only computed for completed runs. ``head_sha`` is the
canonical join key back to the pull-requests builder for a PR's CI status.

Every query module embeds this ``SELECT`` as a subquery (see ``_curated``);
nothing registers it as a global HogQL view.
"""

SOURCE_TABLE = "github_workflow_runs"


def build_query() -> str:
    repo_full_name = "JSONExtractString(repository, 'full_name')"
    return f"""
        SELECT
            id,
            name AS workflow_name,
            head_sha,
            status,
            conclusion,
            run_started_at,
            updated_at,
            created_at,
            if(status = 'completed', dateDiff('second', run_started_at, updated_at), NULL) AS duration_seconds,
            arrayElement(splitByChar('/', {repo_full_name}), 1) AS repo_owner,
            arrayElement(splitByChar('/', {repo_full_name}), 2) AS repo_name
        FROM {SOURCE_TABLE}
    """
