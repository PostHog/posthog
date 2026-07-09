from typing import Literal, get_args

SituationId = Literal[
    "working",
    "in_review",
    "ci_failing",
    "changes_requested",
    "comments_waiting",
    "ready_to_merge",
    "stale",
    "done",
]

SITUATION_IDS: tuple[SituationId, ...] = get_args(SituationId)

SITUATION_PRIORITY: tuple[SituationId, ...] = (
    "done",
    "ready_to_merge",
    "ci_failing",
    "changes_requested",
    "comments_waiting",
    "in_review",
    "working",
    "stale",
)

ATTENTION_SITUATIONS: frozenset[SituationId] = frozenset(
    {"ci_failing", "changes_requested", "comments_waiting", "stale"}
)
