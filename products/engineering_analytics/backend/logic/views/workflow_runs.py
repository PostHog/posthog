"""The workflow runs builder: one row per run, which holds the newest attempt.

``pr_number`` is the run's own-repo ``pull_requests`` association, or the PR that a merge-queue gate
branch lands when ``is_merge_queue``. It is 0 when the run has neither. A read that counts what the
author did (pushes, re-runs) must add ``NOT is_merge_queue``, because the queue made that head commit.
``commit_pr_number`` is the merged PR that produced the head commit, and is the only PR key a
default-branch push has. See SPEC §6 for both keys.

With ``started_floor`` the caller registers the ``{run_started_floor}`` placeholder (see
``run_started_floor_constant``). The parquet scan can prune on that raw-string floor and cannot prune
on a predicate over the parsed ``run_started_at``.
"""

from collections.abc import Sequence

from products.engineering_analytics.backend.logic.merge_queue import source_pr_number_expr

# The actor check stops a contributor from naming a branch like a gate branch to move runs onto
# another PR (see logic.merge_queue).
MERGE_QUEUE_PR_NUMBER = source_pr_number_expr("head_branch", queue_actor_column="JSONExtractString(actor, 'login')")

# The webhook sync can miss the final event of a run, and the row then stays unfinished forever.
# A reader treats such a run as ended at its last update. The run row gives it no outcome, so only a
# failed job row can mark it failed.
STOPPED_REPORTING_SQL = "(status != 'completed' AND updated_at < now() - INTERVAL 1 DAY)"

# GitHub lists every PR in the fork network that shares the run's head SHA, so only an entry based in
# the run's own repo counts. JSONExtractInt yields 0 for an absent key, so the ``> 0`` stops a
# malformed entry from matching a run whose ``repository`` JSON is missing.
_OWN_REPO_PR = """arrayFirst(
                    p -> JSONExtractInt(p, 'base', 'repo', 'id') > 0
                        AND JSONExtractInt(p, 'base', 'repo', 'id') = ifNull(JSONExtractInt(repository, 'id'), 0),
                    JSONExtractArrayRaw(ifNull(pull_requests, '[]'))
                )"""
# For a merge-queue gate run this is the temporary PR the queue opened, not the PR it lands.
ASSOCIATION_PR_NUMBER = f"JSONExtractInt({_OWN_REPO_PR}, 'number')"

# The fallback for ``commit_pr_number`` when the merge-commit join finds no PR. The match is anchored
# to a line end, because the first (#N) in 'Revert "x (#A)" (#B)' names the reverted PR.
_MESSAGE_PR_NUMBER = (
    "accurateCastOrNull("
    "regexpExtract(JSONExtractString(ifNull(head_commit, '{}'), 'message'), '(?m)[(]#([0-9]+)[)]$'), 'Int64')"
)


def _merged_pr_index(pull_requests_table: str) -> str:
    """One row per merge commit SHA, with the lowest number of the merged PRs that carry it.

    The join must see one row per SHA, because a duplicate key multiplies the run rows. The filter on
    ``merged_at`` is required, because an open PR carries a temporary test-merge SHA.
    """
    return f"""
        SELECT
            merge_commit_sha,
            min(number) AS merged_pr_number
        FROM {pull_requests_table}
        WHERE ifNull(merged_at, '') != '' AND ifNull(merge_commit_sha, '') != ''
        GROUP BY merge_commit_sha
    """


def build_query(
    table_name: str,
    *,
    pull_requests_table: str | None = None,
    started_floor: bool = False,
    passthrough: Sequence[str] = (),
) -> str:
    """``passthrough`` names columns of ``table_name`` that the result carries unchanged."""
    extra_columns = "".join(f", {column}" for column in passthrough)
    # The floor needs its own innermost SELECT on the raw string column. The parsing SELECT below
    # aliases the parsed value as run_started_at, so a WHERE there would compare a DateTime with the floor string.
    table_source = (
        f"(SELECT * FROM {table_name} WHERE run_started_at >= {{run_started_floor}})" if started_floor else table_name
    )
    if pull_requests_table:
        merge_join = f"LEFT JOIN ({_merged_pr_index(pull_requests_table)}) AS pr ON run.head_sha = pr.merge_commit_sha"
        # HogQL does not set `join_use_nulls`, so an unmatched LEFT JOIN fills the number with 0 and
        # the `nullIf` is what lets the message fallback apply.
        commit_pr_number = "coalesce(nullIf(pr.merged_pr_number, 0), message_pr_number)"
    else:
        merge_join = ""
        commit_pr_number = "message_pr_number"
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
            merge_queue_pr_number > 0 AS is_merge_queue,
            -- A gate run's own association names the throwaway PR the queue opened; the branch names
            -- the PR being landed, which is the one every surface asks about.
            if(merge_queue_pr_number > 0, merge_queue_pr_number, association_pr_number) AS pr_number,
            {commit_pr_number} AS commit_pr_number,
            if(status = 'completed', dateDiff('second', run_started_at, updated_at), NULL) AS duration_seconds,
            {STOPPED_REPORTING_SQL} AS stopped_reporting,
            arrayElement(repo_parts, 1) AS repo_owner,
            arrayElement(repo_parts, 2) AS repo_name,
            ci_engine, native_run_id, native_workflow_run_id,
            workflow_id,
            event{extra_columns}
        FROM (
            SELECT
                id,
                name AS workflow_name,
                ci_engine, native_run_id, native_workflow_run_id,
                workflow_id,
                event{extra_columns},
                head_sha,
                head_branch,
                status,
                conclusion,
                run_attempt,
                {ASSOCIATION_PR_NUMBER} AS association_pr_number,
                -- ``actor`` is read inline, not via an alias: an alias defined later in this same
                -- SELECT is not reliably resolvable as another expression's input (see the two-layer
                -- note above). It is the account GitHub recorded as triggering the run, which whoever
                -- pushed the branch cannot set — that is what makes it usable as corroboration.
                {MERGE_QUEUE_PR_NUMBER} AS merge_queue_pr_number,
                {_MESSAGE_PR_NUMBER} AS message_pr_number,
                -- repository is GitHub's MINIMAL repository representation: identity and URLs, never a
                -- default_branch (the PR snapshot's base.repo carries that; see query_default_branches).
                splitByChar('/', ifNull(JSONExtractString(repository, 'full_name'), '')) AS repo_parts,
                parseDateTimeBestEffort(run_started_at) AS run_started_at,
                parseDateTimeBestEffort(updated_at) AS updated_at,
                parseDateTimeBestEffort(created_at) AS created_at
            FROM {table_source}
        ) AS run
        {merge_join}
    """
