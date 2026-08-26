import datetime as dt
from uuid import UUID

from temporalio.common import Priority

APPLY_SCANNER_WORKFLOW_NAME = "replay-vision-apply-scanner"
SWEEP_SCANNER_WORKFLOW_NAME = "replay-vision-sweep-scanner"

# How long a cached admission budget admits without re-running the spend aggregates. Spend the
# cache misses (settling receipts, evaluation reservations, failed-observation refunds) stays wrong
# by at most one TTL, and the admission counter itself never goes stale.
ADMISSION_BUDGET_TTL = dt.timedelta(seconds=15)

# Shared by the sweep's children and the on-demand /observe/ trigger; the orphan cutoff below leans on it.
# Must exceed the worst-case failure chain in `workflow.py`, where every phase spends its full schedule_to_close
# budget before the terminal mark runs: create 3m + mark running 3m + fetch 5m + rasterize 40m + upload 20m +
# provider 25m + terminal mark 3m + cleanup 1m = 100m. The 10m headroom covers task-queue scheduling latency
# between phases. If this timeout wins instead of an activity, the workflow's except block never runs and the
# row is stranded in `running` until the reaper's cutoff below.
APPLY_SCANNER_EXECUTION_TIMEOUT = dt.timedelta(minutes=110)


def on_demand_priority(team_id: int) -> Priority:
    """Task priority for user-initiated starts (1 = highest of 5, default 3): Temporal inherits it into
    the rasterize-recording child and its rasterization-queue activity, so on-demand runs jump the sweep
    and backfill backlog on every queue they touch. The fairness key shares priority-1 dispatch across
    teams, so one team's burst cannot starve another team's on-demand work.
    """
    return Priority(priority_key=1, fairness_key=str(team_id))


# A pending/running row is created inside its workflow, and the workflow cannot outlive its execution timeout
# (which spans Temporal-level retries), so any such row older than the timeout plus a margin for clock skew
# and late state writes is provably orphaned.
OBSERVATION_ORPHAN_CUTOFF = APPLY_SCANNER_EXECUTION_TIMEOUT + dt.timedelta(minutes=30)
# Bounds one reaper pass; a backlog beyond this drains across subsequent reconciler ticks.
REAP_ORPHANED_OBSERVATIONS_BATCH_SIZE = 500
# The reaper heartbeats as it works, so an attempt quiet this long is stranded or stalled, not slow.
REAP_ORPHANED_OBSERVATIONS_HEARTBEAT_TIMEOUT = dt.timedelta(seconds=30)

# Per-action vision-action child, fire-and-forgot by the sweep. Name + timeout live here (not in the
# workflow-def module) so the sweep can start it without cross-importing another @wf.defn module.
PROCESS_VISION_ACTION_WORKFLOW_NAME = "process-vision-action"
PROCESS_VISION_ACTION_EXECUTION_TIMEOUT = dt.timedelta(hours=1)

# Running runs older than twice the process execution timeout are provably stuck (the final
# update activity failed or the workflow was terminated without reaching it).
VISION_ACTION_RUN_STUCK_CUTOFF = PROCESS_VISION_ACTION_EXECUTION_TIMEOUT * 2
REAP_STUCK_VISION_ACTION_RUNS_BATCH_SIZE = 500

# An inline scanner is minted just before its scans start, so anything still childless well after a
# scan could have persisted its first observation never had one.
INLINE_SCANNER_REAP_GRACE = APPLY_SCANNER_EXECUTION_TIMEOUT + dt.timedelta(minutes=30)
INLINE_SCANNER_REAP_BATCH_SIZE = 500


def build_process_vision_action_workflow_id(vision_action_id: UUID) -> str:
    """Deterministic id: a still-running action is skipped (WorkflowAlreadyStartedError), not double-fired."""
    return f"{PROCESS_VISION_ACTION_WORKFLOW_NAME}-{vision_action_id}"


SCANNER_SCHEDULE_INTERVAL = dt.timedelta(minutes=5)

# Minimum age of the deep-sweep watermark before a sweep tick runs the full-events-lookback catch-up
# pass that picks up sessions whose matching events were older than the fast pass's narrow window.
# Paired with SWEEP_EVENTS_LOOKBACK: that sets what the fast pass can miss, this sets how long a miss
# waits, so tuning either one moves the same cost-against-latency tradeoff.
DEEP_SWEEP_INTERVAL = dt.timedelta(hours=12)
# ClickHouse budget for one deep query; the pass shares the sweep activity's ~200s timeout with the
# fast query, so it only gets this when enough of the activity is left to spend it.
DEEP_SWEEP_MAX_EXECUTION_SECONDS = 120

# Most ground one deep pass covers. The events scan pads ~50h around whatever window it is given, so
# an unbounded window is both slow and unbounded in cost; a scanner further behind takes more passes
# rather than one huge one. Sized against the longest interval below, not the floor: the padding
# dominates a single pass, so widening the window is much cheaper than shortening the gap.
DEEP_SWEEP_MAX_WINDOW = dt.timedelta(hours=54)
# Ceiling on the deep pass's cadence stretch. Must stay below DEEP_SWEEP_MAX_WINDOW / DEEP_SWEEP_INTERVAL
# with margin: a pass covering less ground than the gap before it falls behind for good.
DEEP_SWEEP_MAX_FACTOR = 3
# The deep pass is priced on its average daily reads over this window, which has to outlast the
# longest interval above or a stretched pass ages out of its own measurement and resets to the floor.
DEEP_SPEND_WINDOW_DAYS = 8
# Daily ClickHouse read budget for the deep pass alone; above it the pass stretches its interval.
# Half the frequent sweep's budget: it is background catch-up, and giving each pass the full budget
# would double the per-scanner ceiling this throttling exists to hold.
DEEP_SWEEP_READ_BUDGET_BYTES_PER_DAY = 100 * 1024**3

# One-off priming pass for a scanner that has never been swept: a few recent recordings scanned on
# the first sweep tick, so the scanner has observations to show without waiting for new sessions.
PRIMING_LOOKBACK = dt.timedelta(hours=24)
PRIMING_SCAN_SESSIONS = 3
PRIMING_MAX_EXECUTION_SECONDS = 30

# Rolling 24h ClickHouse read budget per scanner. Above it, sweeps stretch their effective cadence
# proportionally (skipped ticks batch into the next executed one, so no sessions are missed).
# Sized an order of magnitude above the healthy post-optimization p95 so only pathological
# filter configurations are ever throttled.
SWEEP_READ_BUDGET_BYTES_24H = 200 * 1024**3
# Cadence stretch ceiling: worst case one sweep an hour, so a throttled scanner stays usable.
SWEEP_THROTTLE_MAX_FACTOR = 12

READ_METER_WORKFLOW_NAME = "replay-vision-meter-scanner-reads"
READ_METER_WORKFLOW_ID = "replay-vision-scanner-read-meter"
READ_METER_SCHEDULE_ID = "replay-vision-scanner-read-meter-schedule"
READ_METER_INTERVAL = dt.timedelta(hours=1)
# Must cover the metering activity's retries. Overlap policy is SKIP, so a long run absorbs the next tick.
READ_METER_EXECUTION_TIMEOUT = dt.timedelta(minutes=20)
METER_SCANNER_READS_TIMEOUT = dt.timedelta(minutes=5)

# Children are ABANDONed and don't count against this budget, but activities do: this must cover the
# prompt-suggestion refresh worst case plus the candidate scan, or a slow refresh kills the whole sweep.
# Overlap SKIP means a slow run absorbs later ticks instead of stacking.
SWEEP_WORKFLOW_EXECUTION_TIMEOUT = dt.timedelta(minutes=15)

# The agentic refresh may run several tool rounds. _AGENT_BUDGET_BACKGROUND_S stops new rounds from
# starting, but the in-flight round and the final structured turn can each add up to _MODEL_CALL_TIMEOUT_MS
# on top, so a pathological run can still reach this cap. That costs one skipped daily refresh (single
# attempt, swallowed by the sweep) rather than a retry, and the next tick picks it up.
REFRESH_PROMPT_SUGGESTION_TIMEOUT = dt.timedelta(minutes=5)

# What one sweep tick's activity gets end to end. Its ClickHouse queries share this, so the exclusion
# scan is capped by what the candidate query left rather than by a fixed budget of its own: overrunning
# kills the attempt after the candidates were found, so the tick retries without ever dispatching.
FIND_SCANNER_CANDIDATES_TIMEOUT = dt.timedelta(seconds=200)

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

# Short attempts so one stranded on a dying worker reruns on a live one instead of holding the tick.
REAPER_OP_TIMEOUT = dt.timedelta(seconds=45)
REAPER_OP_SCHEDULE_TO_CLOSE = dt.timedelta(minutes=2)
REAPER_MAX_ATTEMPTS = 3

# The backfill reaper pages through every backfill schedule and only applies fixes at the end, so a
# healthy pass needs minutes; per-page heartbeats catch a dead worker instead of a short attempt cap.
REAP_BACKFILL_SCHEDULES_TIMEOUT = dt.timedelta(minutes=3)
REAP_BACKFILL_SCHEDULES_SCHEDULE_TO_CLOSE = dt.timedelta(minutes=4)
REAP_BACKFILL_SCHEDULES_HEARTBEAT_TIMEOUT = dt.timedelta(seconds=30)

# Priority 1 so a saturated sweep/backfill backlog cannot queue the tick past its execution timeout.
RECONCILER_ACTIVITY_PRIORITY = Priority(priority_key=1, fairness_key="replay-vision-scanner-reconciler")


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

CHECK_SCANNER_BUDGET_TIMEOUT = dt.timedelta(seconds=30)


# Slots at each cap that scheduled dispatch (sweep, backfill) must leave free, so a user-initiated
# observe still admits when scheduled work is saturated; on-demand admission checks the full caps.
ON_DEMAND_RESERVED_SCANNER_SLOTS = 25
ON_DEMAND_RESERVED_TEAM_SLOTS = 50


def in_flight_headroom(scanner_in_flight: int, team_in_flight: int) -> int:
    """Scheduled-dispatch headroom for a sweep or backfill tick: the tighter of the per-scanner and
    per-team caps, minus the slots reserved for on-demand admission.

    The sweep workflow throttles on this and the count activity records the throttled
    metric from it, so the decision and the metric can't drift apart. Pure, so it is safe
    inside deterministic workflow code.
    """
    return min(
        MAX_IN_FLIGHT_APPLIES_PER_SCANNER - ON_DEMAND_RESERVED_SCANNER_SLOTS - scanner_in_flight,
        MAX_IN_FLIGHT_APPLIES_PER_TEAM - ON_DEMAND_RESERVED_TEAM_SLOTS - team_in_flight,
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
