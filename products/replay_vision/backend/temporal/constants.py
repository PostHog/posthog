import datetime as dt
from uuid import UUID

APPLY_SCANNER_WORKFLOW_NAME = "replay-vision-apply-scanner"
SWEEP_SCANNER_WORKFLOW_NAME = "replay-vision-sweep-scanner"

SCANNER_SCHEDULE_INTERVAL = dt.timedelta(minutes=5)

# Children are ABANDONed and don't count against this budget.
SWEEP_WORKFLOW_EXECUTION_TIMEOUT = dt.timedelta(minutes=5)

SCANNER_SCHEDULE_ID_PREFIX = "replay-vision-scanner"
# Search-attribute value stamped on every per-scanner schedule so the reconciler can list them.
SCANNER_SCHEDULE_TYPE = "replay-vision-scanner-sweep"


def scanner_schedule_id(scanner_id: UUID) -> str:
    return f"{SCANNER_SCHEDULE_ID_PREFIX}-{scanner_id}"


RECONCILER_WORKFLOW_NAME = "replay-vision-reconcile-scanner-schedules"
RECONCILER_WORKFLOW_ID = "replay-vision-scanner-reconciler"
RECONCILER_SCHEDULE_ID = "replay-vision-scanner-reconciler-schedule"

# Worst-case latency between a UI scanner edit and its first per-scanner tick.
RECONCILER_INTERVAL = dt.timedelta(minutes=1)
RECONCILER_EXECUTION_TIMEOUT = dt.timedelta(minutes=5)

LIST_ENABLED_SCANNERS_TIMEOUT = dt.timedelta(seconds=60)
LIST_SCANNER_SCHEDULES_TIMEOUT = dt.timedelta(seconds=120)
RECONCILE_SCHEDULE_OP_TIMEOUT = dt.timedelta(seconds=60)


# Capped so `replay-vision-apply-scanner-{scanner_uuid:36}-{session_id}` fits the 255-char `ReplayObservation.workflow_id` column.
MAX_SESSION_ID_LENGTH = 128

# Sessions shorter than this don't carry enough signal for the LLM to analyze.
MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S = 15

# Sessions with less than this much actual interaction are skipped — they're mostly idle.
MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S = 10

# Sessions with more than 1 hour of active interaction take too long to analyze well.
MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S = 3600


# Hard ceiling on a single scanner's concurrently-running apply-scanner workflows. Bounds one bad config
# (broad filter on a high-volume team) from monopolising the shared rasterizer queue + provider concurrency.
MAX_IN_FLIGHT_APPLIES_PER_SCANNER = 50
COUNT_IN_FLIGHT_APPLIES_TIMEOUT = dt.timedelta(seconds=30)


def build_apply_scanner_workflow_id(scanner_id: UUID, session_id: str) -> str:
    """Deterministic Temporal workflow id for one (scanner, session) application."""
    return f"{APPLY_SCANNER_WORKFLOW_NAME}-{scanner_id}-{session_id}"


def replay_vision_distinct_id(team_id: int) -> str:
    """`posthog_distinct_id` for analytics events emitted by Replay Vision when no human user is attributable."""
    return f"replay-vision:{team_id}"
