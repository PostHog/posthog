"""Curated PR draft/ready transitions query builder.

Maps the raw ``github_pr_state_events`` warehouse table (immutable GitHub issue
events, filtered to ``ready_for_review`` / ``convert_to_draft`` by the source)
into parsed, query-able columns. The table is forward-only — rows accrue from
when it is first synced — so a PR with no rows is ambiguous: it was opened ready
(the common case, where ``open_to_merge_seconds`` already is ready→merge) or its
transitions predate the sync. Consumers must treat absence as "not observed",
never "never drafted". Same string-timestamp / Nullable discipline as the other
builders (see ``pull_requests``).
"""


def build_query(table_name: str) -> str:
    # The event filter is re-asserted here (the source already applies it) so the domain rule
    # "this table is draft/ready transitions only" holds even if the source ever widens its sync.
    return f"""
        SELECT
            id,
            event,
            pr_number,
            ifNull(actor_login, '') AS actor_login,
            parseDateTimeBestEffort(created_at) AS created_at
        FROM {table_name}
        WHERE event IN ('ready_for_review', 'convert_to_draft')
    """
