import datetime as dt
from uuid import UUID

APPLY_SCANNER_WORKFLOW_NAME = "replay-vision-apply-scanner"
SWEEP_SCANNER_WORKFLOW_NAME = "replay-vision-sweep-scanner"

# Shared by the sweep's children and the on-demand /observe/ trigger; the orphan cutoff below leans on it.
# Must exceed the worst-case failure chain in `workflow.py`, where every phase spends its full schedule_to_close
# budget before the terminal mark runs: create 3m + mark running 3m + fetch 5m + rasterize 40m + upload 20m +
# provider 25m + terminal mark 3m + cleanup 1m = 100m. The 10m headroom covers task-queue scheduling latency
# between phases. If this timeout wins instead of an activity, the workflow's except block never runs and the
# row is stranded in `running` until the reaper's cutoff below.
APPLY_SCANNER_EXECUTION_TIMEOUT = dt.timedelta(minutes=110)

# A pending/running row is created inside its workflow, and the workflow cannot outlive its execution timeout
# (which spans Temporal-level retries), so any such row older than the timeout plus a margin for clock skew
# and late state writes is provably orphaned.
OBSERVATION_ORPHAN_CUTOFF = APPLY_SCANNER_EXECUTION_TIMEOUT + dt.timedelta(minutes=30)
# Bounds one reaper pass; a backlog beyond this drains across subsequent reconciler ticks.
REAP_ORPHANED_OBSERVATIONS_BATCH_SIZE = 500
REAP_ORPHANED_OBSERVATIONS_TIMEOUT = dt.timedelta(minutes=3)
# The reaper heartbeats between phases; a pass that goes quiet this long is stalled, not slow.
REAP_ORPHANED_OBSERVATIONS_HEARTBEAT_TIMEOUT = dt.timedelta(seconds=60)

# Per-action vision-action child, fire-and-forgot by the sweep. Name + timeout live here (not in the
# workflow-def module) so the sweep can start it without cross-importing another @wf.defn module.
PROCESS_VISION_ACTION_WORKFLOW_NAME = "process-vision-action"
PROCESS_VISION_ACTION_EXECUTION_TIMEOUT = dt.timedelta(hours=1)

# Running runs older than twice the process execution timeout are provably stuck (the final
# update activity failed or the workflow was terminated without reaching it).
VISION_ACTION_RUN_STUCK_CUTOFF = PROCESS_VISION_ACTION_EXECUTION_TIMEOUT * 2
REAP_STUCK_VISION_ACTION_RUNS_BATCH_SIZE = 500
REAP_STUCK_VISION_ACTION_RUNS_TIMEOUT = dt.timedelta(minutes=3)

# An inline scanner is minted just before its scans start, so anything still childless well after a
# scan could have persisted its first observation never had one.
INLINE_SCANNER_REAP_GRACE = APPLY_SCANNER_EXECUTION_TIMEOUT + dt.timedelta(minutes=30)
INLINE_SCANNER_REAP_BATCH_SIZE = 500
INLINE_SCANNER_REAP_TIMEOUT = dt.timedelta(minutes=3)


def build_process_vision_action_workflow_id(vision_action_id: UUID) -> str:
    """Deterministic id: a still-running action is skipped (WorkflowAlreadyStartedError), not double-fired."""
    return f"{PROCESS_VISION_ACTION_WORKFLOW_NAME}-{vision_action_id}"


SCANNER_SCHEDULE_INTERVAL = dt.timedelta(minutes=5)

# Children are ABANDONed and don't count against this budget, but activities do: this must cover the
# prompt-suggestion refresh worst case plus the candidate scan, or a slow refresh kills the whole sweep.
# Overlap SKIP means a slow run absorbs later ticks instead of stacking.
SWEEP_WORKFLOW_EXECUTION_TIMEOUT = dt.timedelta(minutes=15)

# The agentic refresh may run several tool rounds. _AGENT_BUDGET_BACKGROUND_S stops new rounds from
# starting, but the in-flight round and the final structured turn can each add up to _MODEL_CALL_TIMEOUT_MS
# on top, so a pathological run can still reach this cap. That costs one skipped daily refresh (single
# attempt, swallowed by the sweep) rather than a retry, and the next tick picks it up.
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


# Bounded so broker errors surface as activity failures instead of getting lost in the producer buffer.
KAFKA_DELIVERY_TIMEOUT_S = 10.0


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


def in_flight_headroom(scanner_in_flight: int, team_in_flight: int) -> int:
    """Dispatch headroom for a sweep tick: the tighter of the per-scanner and per-team caps.

    The sweep workflow throttles on this and the count activity records the throttled
    metric from it, so the decision and the metric can't drift apart. Pure, so it is safe
    inside deterministic workflow code.
    """
    return min(
        MAX_IN_FLIGHT_APPLIES_PER_SCANNER - scanner_in_flight,
        MAX_IN_FLIGHT_APPLIES_PER_TEAM - team_in_flight,
    )


BACKFILL_SCANNER_WORKFLOW_NAME = "replay-vision-backfill-scanner"
BACKFILL_SCHEDULE_ID_PREFIX = "replay-vision-backfill"
# Search-attribute value stamped on every per-backfill schedule so the reconciler can list and reap them.
BACKFILL_SCHEDULE_TYPE = "replay-vision-backfill-tick"

# Each tick dispatches at most the backfill sub-cap, so a short interval keeps throughput bounded by
# in-flight capacity rather than tick cadence; overlap SKIP means a slow tick absorbs the next fire.
BACKFILL_TICK_INTERVAL = dt.timedelta(minutes=1)
# Covers the candidate query's ClickHouse budget plus child dispatch fan-out.
BACKFILL_TICK_EXECUTION_TIMEOUT = dt.timedelta(minutes=10)

PREPARE_BACKFILL_TICK_TIMEOUT = dt.timedelta(seconds=30)
FIND_BACKFILL_CANDIDATES_TIMEOUT = dt.timedelta(seconds=200)
ADVANCE_BACKFILL_CURSOR_TIMEOUT = dt.timedelta(seconds=30)
BACKFILL_SCHEDULE_OP_TIMEOUT = dt.timedelta(seconds=60)
REAP_BACKFILL_SCHEDULES_TIMEOUT = dt.timedelta(minutes=3)

# A backfill's dispatches count toward the shared per-scanner/per-team caps but never fill more than
# this many slots, so live sweeps always retain rasterizer + provider capacity.
MAX_IN_FLIGHT_APPLIES_PER_BACKFILL = 50


def backfill_schedule_id(backfill_id: UUID) -> str:
    return f"{BACKFILL_SCHEDULE_ID_PREFIX}-{backfill_id}"


def backfill_dispatch_budget(scanner_in_flight: int, team_in_flight: int, backfill_in_flight: int) -> int:
    """How many apply-scanner children one backfill tick may dispatch: the shared sweep headroom
    further bounded by the backfill sub-cap. Pure, so it is safe inside deterministic workflow code."""
    return min(
        in_flight_headroom(scanner_in_flight, team_in_flight),
        MAX_IN_FLIGHT_APPLIES_PER_BACKFILL - backfill_in_flight,
    )


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


def build_evaluate_prompt_suggestion_workflow_id(suggestion_id: UUID) -> str:
    """Deterministic id: one evaluation per suggestion (WorkflowAlreadyStartedError on a duplicate trigger)."""
    return f"{EVALUATE_PROMPT_SUGGESTION_WORKFLOW_NAME}-{suggestion_id}"


def replay_vision_distinct_id(team_id: int) -> str:
    """`posthog_distinct_id` for analytics events emitted by Replay Vision when no human user is attributable."""
    return f"replay-vision:{team_id}"
