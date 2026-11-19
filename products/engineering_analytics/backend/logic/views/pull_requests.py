"""The pull requests builder, which every query module embeds as a subquery.

It drops the pull requests a merge queue opens for its gate branches (see ``logic.merge_queue``).
Bots and drafts stay in, because bot-impact analysis reads them.
"""

from products.engineering_analytics.backend.logic.merge_queue import merge_queue_branch_expr
from products.engineering_analytics.backend.logic.reverts import revert_title_expr

# Bots whose handle does not carry GitHub's automatic ``[bot]`` suffix.
KNOWN_BOT_HANDLES: frozenset[str] = frozenset(
    {
        "posthog-bot",
        "dependabot",
        "renovate",
        "github-actions",
    }
)


def _bot_handle_in_list() -> str:
    # The handles are inlined as SQL literals, so this set must never hold user input.
    return ", ".join(f"'{handle}'" for handle in sorted(KNOWN_BOT_HANDLES))


def build_query(table_name: str) -> str:
    return f"""
        SELECT
            id,
            number,
            title,
            author_handle,
            author_avatar_url,
            (author_handle LIKE '%[bot]' OR author_handle IN ({_bot_handle_in_list()})) AS is_bot,
            {revert_title_expr("title")} AS is_revert,
            arrayElement(repo_parts, 1) AS repo_owner,
            arrayElement(repo_parts, 2) AS repo_name,
            arrayMap(label -> JSONExtractString(label, 'name'), JSONExtractArrayRaw(labels_json)) AS labels,
            if(merged_at IS NOT NULL, 'merged', raw_state) AS state,
            is_draft,
            created_at,
            updated_at,
            merged_at,
            closed_at,
            merge_commit_sha,
            head_sha,
            head_branch,
            base_branch,
            default_branch,
            if(merged_at IS NOT NULL, dateDiff('second', created_at, merged_at), NULL) AS open_to_merge_seconds
        FROM (
            SELECT
                id,
                number,
                title,
                state AS raw_state,
                coalesce(draft, false) AS is_draft,
                -- user is Nullable and NULL for a PR by a deleted GitHub account; JSONExtractString
                -- over a NULL Nullable returns NULL, which would violate the non-null Author contract.
                ifNull(JSONExtractString(user, 'login'), '') AS author_handle,
                ifNull(JSONExtractString(user, 'avatar_url'), '') AS author_avatar_url,
                splitByChar('/', ifNull(JSONExtractString(base, 'repo', 'full_name'), '')) AS repo_parts,
                ifNull(labels, '[]') AS labels_json,
                JSONExtractString(head, 'sha') AS head_sha,
                -- head.ref is the PR's source branch — the key a branch → PR resolution matches on.
                JSONExtractString(head, 'ref') AS head_branch,
                -- base.ref is the branch the PR merges into (usually the default branch); the LLM-spend
                -- session join treats it as neutral, since agents stamp pre-branch exploration with it.
                JSONExtractString(base, 'ref') AS base_branch,
                -- base.repo is a full repository object, so unlike the run payload it carries the
                -- repo's reported default branch (see query_default_branches).
                ifNull(JSONExtractString(base, 'repo', 'default_branch'), '') AS default_branch,
                parseDateTimeBestEffort(created_at) AS created_at,
                parseDateTimeBestEffort(updated_at) AS updated_at,
                parseDateTimeBestEffort(merged_at) AS merged_at,
                parseDateTimeBestEffort(closed_at) AS closed_at,
                -- Terminal only on a merged PR; on an open PR GitHub fills it with a throwaway
                -- test-merge commit, so every read joining on it must gate on merged_at.
                ifNull(merge_commit_sha, '') AS merge_commit_sha
            FROM {table_name}
        )
        WHERE NOT {merge_queue_branch_expr("head_branch", queue_actor_column="author_handle")}
    """
