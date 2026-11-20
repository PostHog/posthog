"""The reviews builder. The source drops PENDING drafts, so every row is a submitted review.

``state`` is uppercased because the webhook path can land a lowercase verdict.
"""

from products.engineering_analytics.backend.logic.bots import bot_handle_expr

APPROVED_STATE = "APPROVED"
CHANGES_REQUESTED_STATE = "CHANGES_REQUESTED"


def build_query(table_name: str) -> str:
    return f"""
        SELECT id, pr_number, reviewer_login, {bot_handle_expr("reviewer_login")} AS reviewer_is_bot, state, submitted_at
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
