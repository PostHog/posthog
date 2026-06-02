"""The ``engineering_analytics_pull_requests`` curated read layer.

A per-team HogQL view that maps the raw ``github_pull_requests`` warehouse
snapshot (GitHub's PR JSON, landed verbatim) into honest, query-able columns.
This is the ONLY place PR domain rules live — bot detection, repo identity from
``base.repo.full_name``, label extraction, the canonical PR state, and the
coarse open-to-merge duration. Every surface (the SQL/MCP tool, ``pr_lifecycle``,
the future UI) reads these columns instead of re-deriving them from JSON.
"""

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    SavedQuery,
    StringArrayDatabaseField,
    StringDatabaseField,
)

VIEW_NAME = "engineering_analytics_pull_requests"
SOURCE_TABLE = "github_pull_requests"

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

FIELDS: dict[str, FieldOrTable] = {
    "id": IntegerDatabaseField(name="id"),
    "number": IntegerDatabaseField(name="number"),
    "title": StringDatabaseField(name="title"),
    "author_handle": StringDatabaseField(name="author_handle"),
    "author_avatar_url": StringDatabaseField(name="author_avatar_url"),
    "is_bot": BooleanDatabaseField(name="is_bot"),
    "repo_owner": StringDatabaseField(name="repo_owner"),
    "repo_name": StringDatabaseField(name="repo_name"),
    "labels": StringArrayDatabaseField(name="labels"),
    "state": StringDatabaseField(name="state"),
    "is_draft": BooleanDatabaseField(name="is_draft"),
    "created_at": DateTimeDatabaseField(name="created_at"),
    "merged_at": DateTimeDatabaseField(name="merged_at", nullable=True),
    "closed_at": DateTimeDatabaseField(name="closed_at", nullable=True),
    "head_sha": StringDatabaseField(name="head_sha"),
    "open_to_merge_seconds": IntegerDatabaseField(name="open_to_merge_seconds", nullable=True),
}


def _bot_handle_in_list() -> str:
    # Hardcoded allowlist, never user input — safe to inline as SQL literals.
    return ", ".join(f"'{handle}'" for handle in sorted(KNOWN_BOT_HANDLES))


def build_query() -> str:
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
        FROM {SOURCE_TABLE}
    """


def build_view() -> SavedQuery:
    return SavedQuery(id=VIEW_NAME, name=VIEW_NAME, query=build_query(), fields=FIELDS)
