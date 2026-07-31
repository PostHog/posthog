"""Curated PR draft/ready transitions query builder.

Maps the raw ``github_issue_events`` warehouse table (immutable GitHub issue events of
every type, landed verbatim) into the transitions-only rows the ready-to-merge metric
reads. The transition vocabulary and the "transitions only" domain rule live here once;
consumers import the event constants rather than restating the raw strings.

GitHub's ``ready_for_review`` / ``convert_to_draft`` timestamps exist ONLY as issue
events (the PR snapshot carries just a ``draft`` bool that transitions overwrite), and
GitHub caps the endpoint's history walk, so the table covers a bounded recent window
that grows forward from the first sync. A PR with no transition rows is therefore
ambiguous — opened ready, or its flips predate the window — which is why
``build_window_start_query`` exists: the minimum event timestamp over the WHOLE table
(every event type, not just transitions) marks how far back observation reaches, because
the desc walk lands a contiguous newest-to-oldest range. A merged PR with no transitions
that was created inside that window verifiably never left ready. Same string-timestamp /
Nullable discipline as the other builders (see ``pull_requests``).
"""

# GitHub's issue-event vocabulary for the draft/ready transitions.
READY_FOR_REVIEW_EVENT = "ready_for_review"
CONVERT_TO_DRAFT_EVENT = "convert_to_draft"


def build_query(table_name: str) -> str:
    # Two layers like ``pull_requests``: the inner SELECT parses/extracts, the outer filters —
    # a row whose timestamp parses to NULL cannot be ordered and would poison the per-PR argMax.
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
