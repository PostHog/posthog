import datetime as dt
from uuid import UUID

APPLY_SCANNER_WORKFLOW_NAME = "replay-vision-apply-scanner"
SWEEP_SCANNER_WORKFLOW_NAME = "replay-vision-sweep-scanner"

# Shared by the sweep's children and the on-demand /observe/ trigger; the orphan cutoff below leans on it.
APPLY_SCANNER_EXECUTION_TIMEOUT = dt.timedelta(hours=1)

# Pending/running rows older than twice the apply execution timeout are provably orphaned.
OBSERVATION_ORPHAN_CUTOFF = APPLY_SCANNER_EXECUTION_TIMEOUT * 2
# Bounds one reaper pass; a backlog beyond this drains across subsequent reconciler ticks.
REAP_ORPHANED_OBSERVATIONS_BATCH_SIZE = 500
REAP_ORPHANED_OBSERVATIONS_TIMEOUT = dt.timedelta(minutes=3)

# Per-action vision-action child, fire-and-forgot by the sweep. Name + timeout live here (not in the
# workflow-def module) so the sweep can start it without cross-importing another @wf.defn module.
PROCESS_VISION_ACTION_WORKFLOW_NAME = "process-vision-action"
PROCESS_VISION_ACTION_EXECUTION_TIMEOUT = dt.timedelta(hours=1)


def build_process_vision_action_workflow_id(vision_action_id: UUID) -> str:
    """Deterministic id: a still-running action is skipped (WorkflowAlreadyStartedError), not double-fired."""
    return f"{PROCESS_VISION_ACTION_WORKFLOW_NAME}-{vision_action_id}"


SCANNER_SCHEDULE_INTERVAL = dt.timedelta(minutes=5)

# Children are ABANDONed and don't count against this budget, but activities do: this must cover the
# prompt-suggestion refresh worst case plus the candidate scan, or a slow refresh kills the whole sweep.
# Overlap SKIP means a slow run absorbs later ticks instead of stacking.
SWEEP_WORKFLOW_EXECUTION_TIMEOUT = dt.timedelta(minutes=15)

# The agentic refresh may run several tool rounds and up to two cold summaries. Its in-process budget
# (_AGENT_BUDGET_BACKGROUND_S) keeps typical runs well under this, so the activity finishes cleanly and
# a suggestion lands; this cap is the backstop for a hung provider.
REFRESH_PROMPT_SUGGESTION_TIMEOUT = dt.timedelta(minutes=5)

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

# Bounded so broker errors surface as activity failures instead of getting lost in the producer buffer.
KAFKA_DELIVERY_TIMEOUT_S = 10.0

# Sessions shorter than this don't carry enough signal for the LLM to analyze.
MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S = 15

# Sessions with less than this much actual interaction are skipped — they're mostly idle.
MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S = 10

# Sessions with more than 1 hour of active interaction take too long to analyze well.
MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S = 3600


# Signals source identity — must match the registered (SourceProduct, SourceType) pair and schema variant.
# Prefixed so it stays unambiguous when imported alongside other products' signal-source constants.
VISION_SIGNALS_SOURCE_PRODUCT = "replay_vision"
VISION_SIGNALS_SOURCE_TYPE = "scanner_finding"


# Hard ceiling on a single scanner's concurrently-running apply-scanner workflows. Bounds one bad config
# (broad filter on a high-volume team) from monopolising the shared rasterizer queue + provider concurrency.
MAX_IN_FLIGHT_APPLIES_PER_SCANNER = 150
# Team-wide ceiling across all of a team's scanners and on-demand triggers, so N scanners can't hold
# N x 150 rasterizer slots. Fairness only; the rasterizer scales horizontally for total throughput.
MAX_IN_FLIGHT_APPLIES_PER_TEAM = 300
COUNT_IN_FLIGHT_APPLIES_TIMEOUT = dt.timedelta(seconds=30)


ESTIMATES_WORKFLOW_NAME = "replay-vision-refresh-scanner-estimates"
ESTIMATES_WORKFLOW_ID = "replay-vision-estimate-refresher"
ESTIMATES_SCHEDULE_ID = "replay-vision-estimate-refresher-schedule"

# Quarter-hourly checks against a 24h staleness target keep estimates at most ~24h15m old.
ESTIMATES_REFRESH_INTERVAL = dt.timedelta(minutes=15)
# Covers the worst-case batch (MAX_PER_RUN / CONCURRENCY × the 60s activity timeout = 100 min) with margin;
# overlap SKIP means a slow run absorbs later ticks instead of being cancelled mid-batch.
ESTIMATES_EXECUTION_TIMEOUT = dt.timedelta(hours=2)

# Each refresh is a ClickHouse count; bound the batch and parallelism so one run stays cheap.
ESTIMATES_MAX_PER_RUN = 400
ESTIMATE_REFRESH_CONCURRENCY = 4

LIST_STALE_ESTIMATES_TIMEOUT = dt.timedelta(seconds=60)
# Covers the estimate query's 30s ClickHouse cap plus the Postgres staleness check.
REFRESH_SCANNER_ESTIMATE_TIMEOUT = dt.timedelta(seconds=60)


def build_apply_scanner_workflow_id(scanner_id: UUID, session_id: str) -> str:
    """Deterministic Temporal workflow id for one (scanner, session) application."""
    return f"{APPLY_SCANNER_WORKFLOW_NAME}-{scanner_id}-{session_id}"


EVALUATE_PROMPT_SUGGESTION_WORKFLOW_NAME = "replay-vision-evaluate-prompt-suggestion"
# The execution timeout lives in prompt_evaluation.py to keep it importable from quota.


def build_evaluate_prompt_suggestion_workflow_id(suggestion_id: UUID) -> str:
    """Deterministic id: one evaluation per suggestion (WorkflowAlreadyStartedError on a duplicate trigger)."""
    return f"{EVALUATE_PROMPT_SUGGESTION_WORKFLOW_NAME}-{suggestion_id}"


def replay_vision_distinct_id(team_id: int) -> str:
    """`posthog_distinct_id` for analytics events emitted by Replay Vision when no human user is attributable."""
    return f"replay-vision:{team_id}"
