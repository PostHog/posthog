"""Curated pull-requests query builder.

Maps the raw GitHub pull-requests warehouse snapshot (GitHub's PR JSON, landed
verbatim) into honest, query-able columns. This is the ONLY place PR-snapshot domain
rules live — bot detection, repo identity from ``base.repo.full_name``, the repo's
reported default branch, label extraction, the canonical PR state, and the coarse
open-to-merge duration; the draft/ready-transition rules live once in ``issue_events`` +
``_curated``. The source table name is resolved per-team and passed in (see
``logic.sources``); it is never hardcoded, because a warehouse table's name is
``prefix + "github_pull_requests"`` and the prefix is user-chosen. Every query module
embeds this ``SELECT`` as a subquery (see ``_curated``) rather than re-deriving the
columns from JSON; nothing registers it as a global HogQL view, so the product stays
off the per-query catalog hot path.

Merge-queue gate branches are filtered out here (see ``logic.merge_queue``). A queue opens a
draft PR per merge attempt — a third of this repo's PR rows — and those are CI artifacts, not
units of work: they carry no diff of their own, never merge, and no PR surface can act on one.
The filter pairs the branch shape with the PR's author, because a branch name is contributor-
controlled: on the shape alone, opening a PR from a branch named ``trunk-merge/pr-123/x`` would
delete it from every surface here.
Dropping them at the builder is deliberately unlike the bot/draft rule, which stays a per-read
default so bot-impact analysis can still see bots (SPEC §6). Nothing is lost for attribution:
the gate branch's *runs* stay in the runs substrate, re-keyed to the PR they were landing.

The real GitHub source lands timestamps as **strings** and the nested objects
(``user`` / ``head`` / ``base`` / ``labels``) as **Nullable** JSON, so this builder
runs in two layers: an inner SELECT parses each timestamp with
``parseDateTimeBestEffort`` and unwraps the Nullable JSON with ``ifNull`` (a
Nullable column cannot feed ``JSONExtractArrayRaw`` / ``splitByChar`` — ClickHouse
rejects an Array nested inside a Nullable); the outer SELECT then derives state, repo
identity, labels and the duration off those parsed columns. Splitting the layers also
avoids referencing a same-SELECT alias as another expression's input.
"""

from products.engineering_analytics.backend.logic.merge_queue import merge_queue_branch_expr

# Bots whose handle does not carry GitHub's automatic ``[bot]`` suffix. Kept
# deliberately small; per-team configuration is deferred.
KNOWN_BOT_HANDLES: frozenset[str] = frozenset(
    {
        "posthog-bot",
        "dependabot",
        "renovate",
        "github-actions",
    }
)


def _bot_handle_in_list() -> str:
    # Hardcoded allowlist, never user input — safe to inline as SQL literals.
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
            arrayElement(repo_parts, 1) AS repo_owner,
            arrayElement(repo_parts, 2) AS repo_name,
            arrayMap(label -> JSONExtractString(label, 'name'), JSONExtractArrayRaw(labels_json)) AS labels,
            if(merged_at IS NOT NULL, 'merged', raw_state) AS state,
            is_draft,
            created_at,
            updated_at,
            merged_at,
            closed_at,
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
                parseDateTimeBestEffort(closed_at) AS closed_at
            FROM {table_name}
        )
        WHERE NOT {merge_queue_branch_expr("head_branch", queue_actor_column="author_handle")}
    """
