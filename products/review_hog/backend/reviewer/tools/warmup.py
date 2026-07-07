"""Warm-up stage prompts for the fork experiment (`WARMUP_FORK_ENABLED`).

One neutral read-only agent per chunk investigates the chunk and its surroundings; its raw session
transcript becomes the shared, cached prefix every review unit for the chunk forks from. The prompt
must stay judgment-free: the forked prefix is shared by every perspective, so any analysis in it
would anchor all of them (the C5 lesson) — it may contain only raw reads.
"""

import json

from pydantic import BaseModel

from products.review_hog.backend.reviewer.constants import WARMUP_READ_BUDGET_TOKENS
from products.review_hog.backend.reviewer.models.github_meta import PRFile
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk


class WarmUpResult(BaseModel):
    """The warm-up's end-of-turn receipt — inventory only, no analysis."""

    files_read: list[str]
    status: str


class WarmUpSettleAck(BaseModel):
    """The settling turn's minimal acknowledgment."""

    status: str


WARMUP_SYSTEM_PROMPT = (
    "You are preparing shared ground for a code review: a read-only investigation of a PR chunk.\n"
    "HARD RULES: no judgments, no analysis, no opinions, no problem-spotting, no code changes —\n"
    "even if you notice issues, do not mention them. Your transcript will be reused as neutral\n"
    "context by several independent reviewers; anything evaluative in it would bias all of them."
)

# The one extra turn after the investigation. A forked follower's appended user message strips
# prior thinking blocks server-side, so the warm-up itself must end with a trivial user turn —
# that write is what makes the session's final form cheap to replay.
WARMUP_SETTLE_PROMPT = 'Investigation complete. Reply with JSON only: {"status": "ready"}'

# Prefixed onto a forked unit's own prompt so the model builds on the inherited investigation
# instead of re-deriving it. Constraint 6 (locked): skipping re-investigation is the expected
# outcome, not a rule — the unit keeps full tools and may read anything it needs.
FORKED_UNIT_CONTEXT_NOTE = (
    "NOTE: a read-only investigation of this chunk's files and their callers is already in your "
    "context above. Build on it — re-read a file only when you need a detail it did not cover."
)

# Every forked unit's FIRST turn, byte-identical across siblings by design: prompt-cache entries
# are addressable only at their end, so siblings can share the big replayed-transcript prefix only
# if their entire first request matches the leader's. The per-perspective review prompt therefore
# arrives as the SECOND turn, after the shared prefix is established (measured: with the review
# prompt in turn 1, zero cross-unit sharing happens — each unit rewrites the full prefix).
FORKED_UNIT_FIRST_TURN_PROMPT = (
    "You are a senior code reviewer about to review one chunk of a GitHub PR. The read-only "
    "investigation above is your shared starting context: treat those file reads and search "
    "results as ground you have already covered. Your specific review perspective and full "
    "instructions arrive in the next message — do not start any work yet. Reply with exactly: OK."
)


def build_warmup_prompt(chunk: Chunk, pr_files: list[PRFile]) -> str:
    """Render the warm-up's investigation prompt for one chunk.

    Feeds the same per-chunk patch data the review prompt uses, so the warm-up reads exactly the
    ground the reviewers will be asked about; everything else about the instruction is neutral.
    """
    chunk_files = [f.filename for f in chunk.files]
    chunk_patches = [f.model_dump(mode="json") for f in pr_files if f.filename in chunk_files]
    file_list = "\n".join(f"- {name}" for name in chunk_files)
    return f"""Investigate the current state of this repository around one chunk of a PR, read-only.

The chunk's files:
{file_list}

The PR's changes to these files (unified diff hunks):
```json
{json.dumps(chunk_patches, indent=2)}
```

Do, in order:
1. Read each chunk file in full (the checked-out version already contains the changes).
2. For each, find its direct importers/callers (grep) and read the 1-2 most relevant caller files.
3. Read the tests covering these files, if any exist.

Stay within roughly {WARMUP_READ_BUDGET_TOKENS:,} tokens of file content — prefer the files most
connected to the changed lines over exhaustive coverage.

Remember the hard rules: reads only — no judgments, no analysis, no descriptions of problems.

End your turn with JSON only: {{"files_read": ["..."], "status": "done"}}"""
