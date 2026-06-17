"""Curated workflow-runs query builder.

Maps the raw GitHub workflow-runs warehouse snapshot into honest CI columns:
``status`` and ``conclusion`` are passed through unchanged (a conclusion can be
stale until the ``workflow_run`` webhook settles it — see SPEC §9), and
``duration_seconds`` is only computed for completed runs. ``head_sha`` is the
canonical join key back to the pull-requests builder for a PR's CI status. The
source table name is resolved per-team and passed in (see ``logic.sources``); it is
never hardcoded, because a warehouse table's name carries the user-chosen source prefix.

Every query module embeds this ``SELECT`` as a subquery (see ``_curated``);
nothing registers it as a global HogQL view.
"""


def build_query(table_name: str) -> str:
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
        FROM {table_name}
    """
