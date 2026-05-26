from uuid import UUID

APPLY_SCANNER_WORKFLOW_NAME = "replay-vision-apply-scanner"

# Capped so `replay-vision-apply-scanner-{scanner_uuid:36}-{session_id}` fits the 255-char `ReplayObservation.workflow_id` column.
MAX_SESSION_ID_LENGTH = 128

# Sessions shorter than this don't carry enough signal for the LLM to analyze.
MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S = 15

# Sessions with less than this much actual interaction are skipped — they're mostly idle.
MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S = 10

# Sessions with more than 1 hour of active interaction take too long to analyze well.
MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S = 3600


def build_apply_scanner_workflow_id(scanner_id: UUID, session_id: str) -> str:
    """Deterministic Temporal workflow id for one (scanner, session) application."""
    return f"{APPLY_SCANNER_WORKFLOW_NAME}-{scanner_id}-{session_id}"


def replay_vision_distinct_id(team_id: int) -> str:
    """`posthog_distinct_id` for analytics events emitted by Replay Vision when no human user is attributable."""
    return f"replay-vision:{team_id}"
