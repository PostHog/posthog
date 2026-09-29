"""Curated pull request reviews query builder.

The review verdict vocabulary lives here once, so consumers import the constants rather than
restating the strings.

The source drops PENDING drafts, so every row is a submitted review. The webhook path reshapes events
into the polled REST shape, so ``upper`` normalizes the state and a lowercase verdict cannot miss the
approval filter.
"""

APPROVED_STATE = "APPROVED"
CHANGES_REQUESTED_STATE = "CHANGES_REQUESTED"


def build_query(table_name: str) -> str:
    # A row with no parsable submitted_at cannot be ordered against the PR's other events.
    return f"""
        SELECT id, pr_number, reviewer_login, state, submitted_at
        FROM (
            SELECT
                id,
                ifNull(pr_number, 0) AS pr_number,
                ifNull(JSONExtractString(user, 'login'), '') AS reviewer_login,
                upper(ifNull(state, '')) AS state,
                parseDateTimeBestEffort(submitted_at) AS submitted_at
            FROM {table_name}
        )
        WHERE submitted_at IS NOT NULL AND pr_number > 0
    """
