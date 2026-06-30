"""Curated pull-requests query builder.

Maps the raw GitHub pull-requests snapshot (PR JSON, landed verbatim) into honest query-able columns.
The ONLY place PR domain rules live — bot detection, repo identity from ``base.repo.full_name``, label
extraction, canonical PR state, the coarse open-to-merge duration. The source table name is resolved
per-team and passed in (see ``logic.sources``); never hardcoded.

The real source lands timestamps as strings and nested objects (``user`` / ``head`` / ``base`` /
``labels``) as Nullable JSON, so this runs in two layers: an inner SELECT parses timestamps with
``parseDateTimeBestEffort`` and unwraps Nullable JSON with ``ifNull`` (ClickHouse rejects an Array
nested inside a Nullable); the outer SELECT derives state, repo identity, labels, and the duration off
the parsed columns. Splitting also avoids referencing a same-SELECT alias as another expression's input.
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
