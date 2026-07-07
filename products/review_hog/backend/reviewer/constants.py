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

# SANDBOX
# Per-child-workflow fan-out width: each Temporal fan-out (review / validate) bounds its concurrent
# sandbox-turn activities with a fresh `asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)`. The true global
# ceiling is the tasks-task-queue worker's own concurrency, where the sandboxes execute.
MAX_CONCURRENT_SANDBOXES = 10

# A fan-out stage (review / validate) degrades best-effort while at most this fraction of
# its units fail; above it the run fails loudly instead of finalizing a near-empty review as success
# (a total wipeout — e.g. the sandbox layer down — must not look like a clean PR).
FAN_OUT_FAILURE_FLOOR = 0.70

# Severity order backing the urgency-threshold comparison.
_PRIORITY_RANK = {IssuePriority.CONSIDER: 0, IssuePriority.SHOULD_FIX: 1, IssuePriority.MUST_FIX: 2}

# The threshold applied when no per-user setting is available (matches `ReviewUserSettings`' default).
DEFAULT_URGENCY_THRESHOLD = IssuePriority.SHOULD_FIX


def published_priorities_for(threshold: IssuePriority) -> set[IssuePriority]:
    """Priorities at or above the acting user's urgency threshold — the set that gates publishing.

    Shared by the body renderer and the publisher so the two never drift. A pure priority filter:
    findings below the threshold are dropped everywhere; placement (inline vs body) is unchanged.
    """
    return {priority for priority, rank in _PRIORITY_RANK.items() if rank >= _PRIORITY_RANK[threshold]}


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


# BLIND-SPOT CHECK
# Reserved pass number for the blind-spot unit. Fixed and far above any wave enumeration (passes
# 1..N over enabled perspectives), so persisted (pass, chunk) resume keys never collide with a wave
# pass when the enabled set changes between executions at the same head.
BLIND_SPOT_PASS_NUMBER = 1000


# WARM-UP + FORK (experiment arm — eval/experiments/2026-07-warmup-fork/PLAN.md)
# When enabled, each chunk first runs one neutral read-only warm-up agent whose raw session
# transcript is persisted; every review unit for that chunk (wave + blind-spot) then forks from it,
# inheriting the investigation from Anthropic's prompt cache instead of re-deriving it per unit.
# Off = byte-for-byte today's pipeline (the eval control). A failed warm-up degrades its chunk to
# the unforked fan-out, never fails it.
WARMUP_FORK_ENABLED = False

# How long the warm-up activity waits for the raw transcript artifact to land on the warm-up's
# TaskRun after the session ends (uploaded fire-and-forget at turn end by the agent harness).
WARMUP_TRANSCRIPT_WAIT_SECONDS = 90

# Soft reading budget the warm-up prompt states (tokens of file content, guidance not enforced) —
# keeps the shared forked prefix well under the request-size cliff while covering the chunk.
WARMUP_READ_BUDGET_TOKENS = 50_000

# Head start the first forked unit of a chunk gets before its siblings launch. A cache entry
# becomes readable only once the writer's response has STARTED, and snapshot-restore provisioning
# is uniform enough (~±10s) that simultaneously-launched siblings land inside the write window and
# each rewrite the shared prefix instead of reading it (measured: 3/3 collided with no head start).
# 30s still lost one collision — time-to-first-token on a ~96K-token prefix write can exceed it —
# so 60s. One head start suffices: once the leader's entry is readable, all later units read it.
FORK_LEADER_HEAD_START_SECONDS = 60
