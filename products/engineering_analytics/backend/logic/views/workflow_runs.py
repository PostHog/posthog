"""Curated workflow-runs query builder.

Maps the raw GitHub workflow-runs warehouse snapshot into honest CI columns:
``status`` and ``conclusion`` are passed through unchanged (a conclusion can be
stale until the ``workflow_run`` webhook settles it — see SPEC §7), and
``duration_seconds`` is only computed for completed runs. ``head_sha`` is the
canonical join key back to the pull-requests builder for a PR's CI status, while
``pr_number`` keys the per-PR push / re-run rollup and ``run_attempt`` distinguishes
re-runs. The source table name is resolved per-team and passed in (see
``logic.sources``); it is never hardcoded, because a warehouse table's name carries
the user-chosen source prefix.

``pr_number`` is the first entry of the run's ``pull_requests`` association **whose base repo
is this run's own repo**. That filter is load-bearing, not defensive: GitHub populates the
association with every PR in the fork network whose head SHA matches the run, so a push to
``PostHog/posthog:master`` arrives carrying the downstream forks' open "sync from upstream"
PRs (``Mu-L/posthog-1#1379``, ``em3ndez/posthog#3``, ...). Taking the first entry unfiltered
credited ~14% of runs to a stranger's PR number, and — since the number was then paired with
this repo's owner/name — linked it to an unrelated PR of ours. Only an entry whose
``base.repo.id`` equals the run's ``repository.id`` describes a PR this run actually ran for.

Two cases still extract ``0``: a run with no own-repo association (fork PRs, and pushes to a
branch with no open PR), which is filtered out of the rollup (it only counts ``pr_number > 0``);
and a run shared across more than one of our PRs (uncommon — one head tied to multiple open PRs),
which is credited to its first PR only, not fanned out across all of them. That's a deliberate v1
simplification: the rollup is an approximate friction signal (pushes / re-runs), not billing.

``commit_pr_number`` is the complementary key: it is how a push run gets PR attribution at all,
since a merged commit on the default branch has no association of its own. Consumers prefer
``pr_number`` and fall back to this (SPEC §6, "two PR keys, by design"); ``ci_job_history``
exposes both under these names.

It resolves in two steps. The authoritative one is a join to the PR snapshot on
``merge_commit_sha``: the commit GitHub records when a PR merges *is* this run's ``head_sha``, so
the merged PR that produced the commit is a lookup rather than an inference. The head commit's
squash-merge ``(#NNNN)`` suffix is the fallback, for the two cases the join cannot serve: a repo
whose ``pull_requests`` endpoint isn't synced (``pull_requests_table=None``), and a commit whose PR
row hasn't landed in the snapshot yet. Measured over 30 days of ``PostHog/posthog`` default-branch
runs, the join agreed with the suffix on all 122,743 runs the suffix resolved and attributed 35
more that it could not (a merge-commit landing whose subject carries no ``(#NNNN)``).

This is *not* the head-SHA join SPEC §6 locks out; see that entry for why a **merged** PR's
``merge_commit_sha`` is a terminal key rather than the mutable current head the ban is about.

The real GitHub source lands timestamps as **strings** and ``repository`` /
``pull_requests`` as **Nullable** JSON, so this builder runs in two layers: an inner
SELECT parses each timestamp with ``parseDateTimeBestEffort`` and unwraps the
Nullable JSON with ``ifNull`` (a Nullable column cannot feed ``JSONExtractArrayRaw`` /
``splitByChar`` — ClickHouse rejects an Array nested inside a Nullable); the outer
SELECT derives the duration and repo identity off those parsed columns, which also
avoids referencing a same-SELECT alias as another expression's input.

Because those timestamps land as zero-padded ISO-8601 strings, they compare correctly
lexicographically ('2026-07-11' < '2026-07-11T09:00:00'). Every windowed consumer filters
on ``parseDateTimeBestEffort(run_started_at)``, and a predicate over a computed column cannot
be pushed down to the parquet/S3 scan — so each windowed query full-scans the runs table. With
``started_floor`` the builder wraps the source in an innermost prefilter on the RAW string column
(``run_started_at >= {run_started_floor}``), a coarse floor the scan CAN prune on. The precise
parsed ``{date_from}`` filter downstream stays the authoritative bound; the raw floor only trims
the scan. Callers register the ``{run_started_floor}`` placeholder via ``run_started_floor_constant``
(a date-only string one day below the window start, so it can never cut a row the parsed filter keeps).

Every query module embeds this ``SELECT`` as a subquery (see ``_curated``);
nothing registers it as a global HogQL view.
"""

# The run's PR association, narrowed to PRs based in the run's OWN repo (see module docstring).
# ``> 0`` guards the both-missing case: JSONExtractInt yields 0 for an absent key, so a malformed
# entry would otherwise "match" a run whose ``repository`` JSON never landed.
_OWN_REPO_PR = """arrayFirst(
                    p -> JSONExtractInt(p, 'base', 'repo', 'id') > 0
                        AND JSONExtractInt(p, 'base', 'repo', 'id') = ifNull(JSONExtractInt(repository, 'id'), 0),
                    JSONExtractArrayRaw(ifNull(pull_requests, '[]'))
                )"""

# The squash-merge PR number off the head commit's subject: the fallback when the merge-commit
# join can't resolve the run (see module docstring). Anchored to a line end ((?m), the squash
# title): an unanchored match would take the FIRST (#N) in the message, misattributing reverts
# ('Revert "x (#A)" (#B)') to the reverted PR instead of the reverting one.
_MESSAGE_PR_NUMBER = (
    "accurateCastOrNull("
    "regexpExtract(JSONExtractString(ifNull(head_commit, '{}'), 'message'), '(?m)[(]#([0-9]+)[)]$'), 'Int64')"
)


def _merged_pr_index(pull_requests_table: str) -> str:
    """Merged PRs keyed by the commit their merge produced: the default-branch attribution lookup.

    Deduped to one row per SHA: a LEFT JOIN on a non-unique key fans one run row out into several,
    which would silently multiply every count built on this builder. ``min`` breaks the tie
    deterministically rather than correctly, which is the honest trade. GitHub reuses a merge SHA
    only for PRs that landed together, and one SHA in all of ``PostHog/posthog`` carries three.
    """
    return f"""
        SELECT
            merge_commit_sha,
            min(number) AS merged_pr_number
        FROM {pull_requests_table}
        WHERE ifNull(merged_at, '') != '' AND ifNull(merge_commit_sha, '') != ''
        GROUP BY merge_commit_sha
    """


def build_query(table_name: str, *, pull_requests_table: str | None = None, started_floor: bool = False) -> str:
    # The raw floor must live in its OWN innermost SELECT, not the parsing SELECT below: that SELECT
    # aliases parseDateTimeBestEffort(run_started_at) AS run_started_at, and ClickHouse alias resolution
    # would make a WHERE there compare the parsed DateTime against the string. Keep it on the raw column.
    table_source = (
        f"(SELECT * FROM {table_name} WHERE run_started_at >= {{run_started_floor}})" if started_floor else table_name
    )
    if pull_requests_table:
        merge_join = f"LEFT JOIN ({_merged_pr_index(pull_requests_table)}) AS pr ON run.head_sha = pr.merge_commit_sha"
        # An unmatched LEFT JOIN fills the Int with 0, not NULL (HogQL doesn't set `join_use_nulls`),
        # so `nullIf` is what lets the message fallback fire on a miss instead of reading PR 0.
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
            default_branch,
            pr_number,
            {commit_pr_number} AS commit_pr_number,
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
                JSONExtractInt({_OWN_REPO_PR}, 'number') AS pr_number,
                {_MESSAGE_PR_NUMBER} AS message_pr_number,
                splitByChar('/', ifNull(JSONExtractString(repository, 'full_name'), '')) AS repo_parts,
                ifNull(JSONExtractString(repository, 'default_branch'), '') AS default_branch,
                parseDateTimeBestEffort(run_started_at) AS run_started_at,
                parseDateTimeBestEffort(updated_at) AS updated_at,
                parseDateTimeBestEffort(created_at) AS created_at
            FROM {table_source}
        ) AS run
        {merge_join}
    """
