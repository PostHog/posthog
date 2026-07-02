from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.tasks.backend.facade.run_config import ReasoningEffort, RuntimeAdapter

# REVIEW MODEL
REVIEW_RUNTIME_ADAPTER = RuntimeAdapter.CLAUDE
REVIEW_MODEL = "claude-opus-4-8"
REVIEW_REASONING_EFFORT = ReasoningEffort.XHIGH
# Claude sandboxes run with bypassPermissions by default, so headless MCP skill pulls need no
# extra approval mode. (Only Codex's default "auto" stalls on MCP calls and needs "full-access".)
REVIEW_INITIAL_PERMISSION_MODE = None

# SANDBOX
# Per-child-workflow fan-out width: each Temporal fan-out (review / validate) bounds its concurrent
# sandbox-turn activities with a fresh `asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)`. The true global
# ceiling is the tasks-task-queue worker's own concurrency, where the sandboxes execute.
MAX_CONCURRENT_SANDBOXES = 10

# A fan-out stage (review / validate) degrades best-effort while at most this fraction of
# its units fail; above it the run fails loudly instead of finalizing a near-empty review as success
# (a total wipeout — e.g. the sandbox layer down — must not look like a clean PR).
FAN_OUT_FAILURE_FLOOR = 0.70

# Priorities surfaced in the review body's per-chunk count and published as inline comments
# (CONSIDER is body-only context). Shared by the body renderer and the publisher so the two never drift.
PUBLISHED_PRIORITIES = {IssuePriority.MUST_FIX, IssuePriority.SHOULD_FIX}


def effective_priority(base: IssuePriority, adjusted: IssuePriority | None) -> IssuePriority:
    """The priority that gates publishing: the validator's override if it set one, else the reviewer's.

    Validator-wins — its deeper per-issue investigation can raise or lower severity; an unset override
    keeps the reviewer's call. Every publish/body gate resolves through this so display and gating agree.
    """
    return adjusted if adjusted is not None else base


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
