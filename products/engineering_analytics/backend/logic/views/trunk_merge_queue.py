TRUNK_OUT_OF_QUEUE_STATES = frozenset({"failed", "cancelled"})


def build_query(table: str) -> str:
    """One row per queue entry. Drops rows that have no state or no transition time."""
    return f"""
    SELECT
        state,
        parseDateTimeBestEffort(state_changed_at) AS state_changed_at,
        ifNull(skip_the_line, false) AS skip_the_line,
        pr_number
    FROM {table}
    WHERE state IS NOT NULL AND state_changed_at IS NOT NULL
"""
