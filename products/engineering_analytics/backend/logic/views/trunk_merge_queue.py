"""Curated view over the Trunk merge-queue snapshot (``TRUNK_MERGE_QUEUE_COLUMNS``)."""


def build_query(table: str) -> str:
    """Curated SELECT over a synced Trunk merge-queue table: parsed last-transition time, the
    terminal-or-current state, and the skip-the-line flag. Rows without a state or transition
    time carry nothing any consumer can window on, so they drop here."""
    return f"""
    SELECT
        state,
        parseDateTimeBestEffort(state_changed_at) AS state_changed_at,
        ifNull(skip_the_line, false) AS skip_the_line,
        pr_number
    FROM {table}
    WHERE state IS NOT NULL AND state_changed_at IS NOT NULL
"""
