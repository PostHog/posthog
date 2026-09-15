"""Curated pull-request reviews query builder.

Maps the raw ``github_reviews`` warehouse table (one row per submitted review, with the PR number
injected by the source's fan-out) into the columns the review reads need. The review verdict
vocabulary lives here once; consumers import the constants rather than restating the strings.

The source drops PENDING drafts before rows land, so every row is a submitted review. The
webhook path reshapes events into the polled REST shape, but ``upper`` still normalizes the
state so a lowercase verdict can never silently miss the approval filter.
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
