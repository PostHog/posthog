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

The real GitHub source lands timestamps as **strings** and the nested objects
(``user`` / ``head`` / ``base`` / ``labels``) as **Nullable** JSON, so this builder
runs in two layers: an inner SELECT parses each timestamp with
``parseDateTimeBestEffort`` and unwraps the Nullable JSON with ``ifNull`` (a
Nullable column cannot feed ``JSONExtractArrayRaw`` / ``splitByChar`` — ClickHouse
rejects an Array nested inside a Nullable); the outer SELECT then derives state, repo
identity, labels and the duration off those parsed columns. Splitting the layers also
avoids referencing a same-SELECT alias as another expression's input.
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
            merged_at,
            closed_at,
            head_sha,
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
                parseDateTimeBestEffort(created_at) AS created_at,
                parseDateTimeBestEffort(merged_at) AS merged_at,
                parseDateTimeBestEffort(closed_at) AS closed_at
            FROM {table_name}
        )
    """
