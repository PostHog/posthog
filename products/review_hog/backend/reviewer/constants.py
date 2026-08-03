from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.tasks.backend.facade.run_config import ReasoningEffort, RuntimeAdapter

# REVIEW MODEL
REVIEW_RUNTIME_ADAPTER = RuntimeAdapter.CLAUDE
REVIEW_MODEL = "claude-sonnet-5"
REVIEW_REASONING_EFFORT = ReasoningEffort.XHIGH
# Claude sandboxes run with bypassPermissions by default, so headless MCP skill pulls need no
# extra approval mode. (Only Codex's default "auto" stalls on MCP calls and needs "full-access".)
REVIEW_INITIAL_PERMISSION_MODE = None

# VALIDATION MODEL
# Pins for the per-chunk warm validation sessions. All-None = the agent server's default model at its
# default effort (the behavior before this knob existed); set all three to pin, like the review pins.
VALIDATION_RUNTIME_ADAPTER: RuntimeAdapter | None = RuntimeAdapter.CLAUDE
VALIDATION_MODEL: str | None = "claude-opus-4-8"
VALIDATION_REASONING_EFFORT: ReasoningEffort | None = ReasoningEffort.XHIGH
VALIDATION_INITIAL_PERMISSION_MODE: str | None = None

# CHUNKING MODEL
# Pins for the sandbox chunking turn (PRs over the one-shot gate), matching the one-shot pin below —
# chunking is organization, not judgment, so both delivery paths run the same cheaper model.
CHUNKING_RUNTIME_ADAPTER = RuntimeAdapter.CLAUDE
CHUNKING_MODEL = "claude-sonnet-5"
CHUNKING_REASONING_EFFORT = ReasoningEffort.XHIGH

# DEDUP MODEL
# Pins for the sandbox dedup turn (finding sets over the one-shot gate) — same rationale as the
# chunking pins: keep both delivery paths of a mechanical stage on the one-shot model.
DEDUP_RUNTIME_ADAPTER = RuntimeAdapter.CLAUDE
DEDUP_MODEL = "claude-sonnet-5"
DEDUP_REASONING_EFFORT = ReasoningEffort.XHIGH

# SANDBOX
# Per-child-workflow fan-out width: each Temporal fan-out (review / validate) bounds its concurrent
# sandbox-turn activities with a fresh `asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)`. The true global
# ceiling is the tasks-task-queue worker's own concurrency, where the sandboxes execute.
MAX_CONCURRENT_SANDBOXES = 10

# A fan-out stage (review / validate) degrades best-effort while at most this fraction of
# its units fail; above it the run fails loudly instead of finalizing a near-empty review as success
# (a total wipeout — e.g. the sandbox layer down — must not look like a clean PR).
FAN_OUT_FAILURE_FLOOR = 0.70

# Attempts for a chunk's warm validation session. Retries are cheap — skip-resume re-validates only
# issues without a persisted verdict. On the final attempt a failed turn is skipped, not raised.
VALIDATION_MAX_ATTEMPTS = 2

# Severity order backing the urgency-threshold comparison.
_PRIORITY_RANK = {IssuePriority.CONSIDER: 0, IssuePriority.SHOULD_FIX: 1, IssuePriority.MUST_FIX: 2}

# The threshold applied when no per-user setting is available (matches `ReviewUserSettings`' default).
DEFAULT_URGENCY_THRESHOLD = IssuePriority.CONSIDER


def published_priorities_for(threshold: IssuePriority) -> set[IssuePriority]:
    """Priorities at or above the acting user's urgency threshold — the set that gates publishing.

    Shared by the body renderer and the publisher so the two never drift. A pure priority filter:
    findings below the threshold are dropped everywhere; placement (inline vs body) is unchanged.
    """
    return {priority for priority, rank in _PRIORITY_RANK.items() if rank >= _PRIORITY_RANK[threshold]}


def priority_rank(priority: IssuePriority) -> int:
    """Severity as a sortable number, ascending: consider < should_fix < must_fix."""
    return _PRIORITY_RANK[priority]


def effective_priority(base: IssuePriority, adjusted: IssuePriority | None) -> IssuePriority:
    """The priority that gates publishing: the validator's override if it set one, else the reviewer's.

    Validator-wins — its deeper per-issue investigation can raise or lower severity; an unset override
    keeps the reviewer's call. Every publish/body gate resolves through this so display and gating agree.
    """
    return adjusted if adjusted is not None else base


# ONE-SHOT (SANDBOX-FREE) CHUNKING + DEDUP
# Chunking and dedup are pure text tasks — their prompts carry everything inline — so within these
# limits they run as a single direct LLM-gateway call (`reviewer/sandbox/direct_llm.py`) instead of
# an agentic sandbox, cutting ~1 min of sandbox provisioning per stage and removing the sandbox
# failure classes. Above a limit (or with it set to 0 = disabled) the stage takes the sandbox path,
# unchanged.
CHUNKING_ONESHOT_MAX_ADDITIONS = 5000  # reviewable ADDED lines, like the other chunking gates
DEDUP_ONESHOT_MAX_FINDINGS = 50  # issues entering dedup (before the positional pre-filter)

# Model pin for the one-shot calls: adaptive thinking at this effort is the Messages-API-native
# expression of "claude-sonnet-5 @ xhigh" — the same semantics the sandbox pins above request.
ONESHOT_MODEL = "claude-sonnet-5"
ONESHOT_REASONING_EFFORT = "xhigh"

# CHUNKING
# Single-chunk gate: a PR within this many reviewable ADDED lines (deletions don't count) skips the
# chunking LLM and is reviewed as one chunk. Above it, the semantic chunker splits at concern seams.
SINGLE_CHUNK_GATE_ADDITIONS = 400

# Per-chunk size (added lines) the LLM chunker aims for. Guidance, not enforced — the prompt forbids
# single-file fragments and refuses to split atomic concerns, so small PRs don't shatter.
CHUNK_TARGET_ADDITIONS = 300

# Soft cap the LLM chunker is told to stay under — guidance, not enforced: split large concerns at
# natural seams rather than emit one mega-chunk, but keep a truly atomic concern whole if it runs over.
CHUNK_SOFT_MAX_ADDITIONS = 600


# OUTCOME TELEMETRY
# The outcome-classifier judge decides whether the commits that landed after review actually
# addressed a finding. Pinned to a model DIFFERENT from the reviewer's (`REVIEW_MODEL` /
# `ONESHOT_MODEL` = claude-sonnet-5): a judge sharing the reviewer's model family would inherit the
# same blind spots the telemetry exists to measure. Effort is "high" — a focused yes/no on a small
# diff, not the reviewer's exhaustive xhigh pass.
OUTCOME_JUDGE_MODEL = "claude-opus-5"
OUTCOME_JUDGE_REASONING_EFFORT = "high"
# The judge's stated reason is persisted with the outcome so a classification can be explained later.
# It is asked for a sentence or two; this only trims a malfunctioning one before it lands in the row.
OUTCOME_JUDGE_REASONING_MAX_CHARS = 2_000
# A post-review commit counts as touching a finding when it changes lines within this many lines of
# the finding's range — absorbs small drift (an import added above, a line renumbered) without
# matching an unrelated edit elsewhere in the same file. The judge is the real arbiter; this only
# gates which findings are worth spending a judge call on.
OUTCOME_LINE_PROXIMITY_WINDOW = 15
# Cap on reports classified per sweep, so one run can't fan out unboundedly across GitHub egress.
OUTCOME_MAX_REPORTS_PER_SWEEP = 50
# Ceiling on judge calls for one report. The per-sweep cap counts reports, but a report accumulates
# findings across every turn it was reviewed, so a PR pushed and re-reviewed repeatedly before
# merging can carry far more line-proximity candidates than one report's share of the classify
# activity's 30-minute budget. Judge calls run sequentially and each can take minutes, so an
# unbounded report would blow the activity ceiling; because outcomes are persisted only after the
# whole report is decided, the retry and every later sweep would replay the same calls and never
# finish it. Candidates past this ceiling settle without a judge call so the report always completes.
OUTCOME_MAX_JUDGE_CALLS_PER_REPORT = 30
# A judge call that fails settles its finding as `judge_failed` rather than throwing away the whole
# report's completed judgments and replaying them next sweep. These two bound that tolerance, because
# an outcome is written once and never re-decided: recording a report's worth of `judge_failed` during
# an LLM outage would destroy that report's telemetry permanently, so a report that looks
# systematically broken is abandoned mid-flight and retried on a later sweep instead.
# Consecutive failures are the fast signal (the gateway is down, so stop spending on it).
OUTCOME_JUDGE_FAILURE_STREAK = 3
# The ratio is the slow one, checked before persisting: it catches a gateway failing intermittently,
# which never trips the streak. Only meaningful once more calls than the streak have been attempted —
# below that the streak rule already governs, and a lone failure on a small report is better recorded
# than retried forever.
OUTCOME_JUDGE_MIN_SUCCESS_RATIO = 0.75
# Ceiling on pending reports a sweep pulls for one team. A report whose PR is closed without merging
# is never classifiable and never stamped, so it stays discoverable forever: without a bound, that
# sediment accumulates through ordinary attrition and every hourly sweep re-materializes it and folds
# it into the warehouse lookup's `numbers` filter, all before the per-sweep report cap is consulted.
# Ordered newest-first so the sediment sinks below live work rather than crowding it out.
OUTCOME_MAX_PENDING_REPORTS_PER_SWEEP = 500
# Extra compares one report may spend beyond the one from its newest published head. A finding is
# judged against the head ITS turn published at, so a PR re-reviewed many times needs one compare per
# distinct base. That is one GitHub read each, so it is bounded: the budget goes to the OLDEST bases,
# whose fixes the newest-base compare cannot see at all, and anything past it falls back to the newest
# base — today's behavior, which under-counts rather than inventing an `addressed`.
OUTCOME_MAX_EXTRA_COMPARE_BASES = 5
# Ceiling on the diff handed to the judge. The evidence is the finding's whole file patch, and a file
# can pick up a large unrelated rewrite between review and merge, which `run_oneshot_review` expects
# its callers to bound. Roughly 25k tokens: orders of magnitude above a normal file patch, so it only
# bites the pathological case rather than routinely trimming the judge's context.
OUTCOME_JUDGE_DIFF_MAX_CHARS = 100_000


# BLIND-SPOT CHECK
# Reserved pass number for the blind-spot unit. Fixed and far above any wave enumeration (passes
# 1..N over enabled perspectives), so persisted (pass, chunk) resume keys never collide with a wave
# pass when the enabled set changes between executions at the same head.
BLIND_SPOT_PASS_NUMBER = 1000
