"""GitHub caps the issue-events history walk, so the table covers a bounded range that grows forward
from the first sync. A PR with no transition rows either opened ready or changed state outside that
range, and the window builders give the range that tells the two cases apart.
"""

READY_FOR_REVIEW_EVENT = "ready_for_review"
CONVERT_TO_DRAFT_EVENT = "convert_to_draft"
# Carries ``requested_team`` when a team, not a person, was asked to review.
REVIEW_REQUESTED_EVENT = "review_requested"


def build_query(table_name: str, *, created_floor: bool = False) -> str:
    # The raw-string floor needs its own innermost SELECT. The SELECT below aliases the parsed timestamp
    # as created_at, so a WHERE there would compare a DateTime with the string. Callers register
    # {event_created_floor}.
    table_source = (
        f"(SELECT * FROM {table_name} WHERE created_at >= {{event_created_floor}})" if created_floor else table_name
    )
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
            FROM {table_source}
            WHERE event IN ('{READY_FOR_REVIEW_EVENT}', '{CONVERT_TO_DRAFT_EVENT}')
        )
        WHERE created_at IS NOT NULL
    """


def build_team_review_requests_query(table_name: str, *, created_floor: bool) -> str:
    """One row per team review request. With ``created_floor``, callers register {event_created_floor}."""
    table_source = (
        f"(SELECT * FROM {table_name} WHERE created_at >= {{event_created_floor}})" if created_floor else table_name
    )
    return f"""
        SELECT pr_number, team_slug, requested_at
        FROM (
            SELECT
                JSONExtractInt(issue, 'number') AS pr_number,
                ifNull(JSONExtractString(requested_team, 'slug'), '') AS team_slug,
                parseDateTimeBestEffort(created_at) AS requested_at
            FROM {table_source}
            WHERE event = '{REVIEW_REQUESTED_EVENT}'
        )
        WHERE team_slug != '' AND requested_at IS NOT NULL
    """


def build_window_start_query(table_name: str) -> str:
    # Every event type bounds the observed range, because the sync lands one contiguous range.
    return f"SELECT min(parseDateTimeBestEffort(created_at)) AS window_start FROM {table_name}"


def build_window_end_query(table_name: str) -> str:
    return f"SELECT max(parseDateTimeBestEffort(created_at)) AS window_end FROM {table_name}"
