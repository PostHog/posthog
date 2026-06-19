"""Curated pull-requests query builder.

Maps the raw GitHub pull-requests warehouse snapshot (GitHub's PR JSON, landed
verbatim) into honest, query-able columns. This is the ONLY place PR domain rules
live — bot detection, repo identity from ``base.repo.full_name``, label extraction,
the canonical PR state, and the coarse open-to-merge duration. The source table name
is resolved per-team and passed in (see ``logic.sources``); it is never hardcoded,
because a warehouse table's name is ``prefix + "github_pull_requests"`` and the prefix
is user-chosen. Every query module embeds this ``SELECT`` as a subquery (see
``_curated``) rather than re-deriving the columns from JSON; nothing registers it as a
global HogQL view, so the product stays off the per-query catalog hot path.
"""

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
    handle = "JSONExtractString(user, 'login')"
    repo_full_name = "JSONExtractString(base, 'repo', 'full_name')"
    return f"""
        SELECT
            id,
            number,
            title,
            {handle} AS author_handle,
            JSONExtractString(user, 'avatar_url') AS author_avatar_url,
            ({handle} LIKE '%[bot]' OR {handle} IN ({_bot_handle_in_list()})) AS is_bot,
            arrayElement(splitByChar('/', {repo_full_name}), 1) AS repo_owner,
            arrayElement(splitByChar('/', {repo_full_name}), 2) AS repo_name,
            arrayMap(label -> JSONExtractString(label, 'name'), JSONExtractArrayRaw(labels)) AS labels,
            if(merged_at IS NOT NULL, 'merged', state) AS state,
            coalesce(draft, false) AS is_draft,
            created_at,
            merged_at,
            closed_at,
            JSONExtractString(head, 'sha') AS head_sha,
            if(merged_at IS NOT NULL, dateDiff('second', created_at, merged_at), NULL) AS open_to_merge_seconds
        FROM {table_name}
    """
