"""Curated PR draft/ready transitions query builder.

The transition vocabulary and the "transitions only" rule live here once; consumers
import the event constants rather than restating the raw strings. GitHub caps the
issue-events history walk, so the table covers a bounded window growing forward from
the first sync: a PR with no transition rows is ambiguous (opened ready, or its flips
just aren't in the window). The window builders disambiguate: the min/max timestamps
over ALL landed event types bound the observed range, because the desc walk lands a
contiguous range; a merged PR with no transitions whose whole open-to-merge life sits
inside that range verifiably never left ready.
"""

# GitHub's issue-event vocabulary for the draft/ready transitions.
READY_FOR_REVIEW_EVENT = "ready_for_review"
CONVERT_TO_DRAFT_EVENT = "convert_to_draft"


def build_query(table_name: str) -> str:
    # A row whose timestamp parses to NULL cannot be ordered and would poison the per-PR argMax.
    return f"""
        SELECT id, event, pr_number, actor_login, created_at
        FROM (
            SELECT
                id,
                event,
                JSONExtractInt(issue, 'number') AS pr_number,
                ifNull(JSONExtractString(actor, 'login'), '') AS actor_login,
                parseDateTimeBestEffort(created_at) AS created_at
            FROM {table_name}
            WHERE event IN ('{READY_FOR_REVIEW_EVENT}', '{CONVERT_TO_DRAFT_EVENT}')
        )
        WHERE created_at IS NOT NULL
    """


def build_window_start_query(table_name: str) -> str:
    return f"SELECT min(parseDateTimeBestEffort(created_at)) AS window_start FROM {table_name}"


def build_window_end_query(table_name: str) -> str:
    return f"SELECT max(parseDateTimeBestEffort(created_at)) AS window_end FROM {table_name}"
