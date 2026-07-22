"""Curated PR draft/ready transitions query builder.

Maps the raw ``github_issue_events`` warehouse table (immutable GitHub issue events of every
type, reduced to a fixed envelope by the source) into the transitions-only view the metric
reads. This is where the transition vocabulary and the "transitions only" domain rule live;
consumers import the event constants from here rather than restating the raw strings.

The table is forward-only (rows accrue from when it is first synced), so a PR with no rows is
ambiguous: it was opened ready (the common case, where ``open_to_merge_seconds`` already is
ready-to-merge) or its transitions predate the sync. Consumers must treat absence as "not
observed", never "never drafted". Same string-timestamp / Nullable discipline as the other
builders (see ``pull_requests``).
"""

# GitHub's issue-event vocabulary for the draft/ready transitions.
READY_FOR_REVIEW_EVENT = "ready_for_review"
CONVERT_TO_DRAFT_EVENT = "convert_to_draft"


def build_query(table_name: str) -> str:
    return f"""
        SELECT
            id,
            event,
            issue_number AS pr_number,
            ifNull(actor_login, '') AS actor_login,
            parseDateTimeBestEffort(created_at) AS created_at
        FROM {table_name}
        WHERE event IN ('{READY_FOR_REVIEW_EVENT}', '{CONVERT_TO_DRAFT_EVENT}')
    """
