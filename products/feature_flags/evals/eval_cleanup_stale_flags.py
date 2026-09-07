"""Phase A evals for the ``cleaning-up-stale-feature-flags`` skill.

Four sandboxed cases: a generic cleanup ask, an unrelated task that mentions a flag
in passing (the skill must stay quiet, and the agent must still edit a file — the
stale-premise guard borrowed from ``eval_instrument_flags``), a direct removal ask
for a key with no repository references, and the same ask for a 40%-rollout flag.

What the suite cannot grade: the sandbox always clones ``posthog/hedgebox`` and
seeders cannot write files into it, so retained-path correctness (does a diff keep
the right branch) and the "report the no-op, open no empty PR" rule are ungraded.
No scorer reads repo files, branches, or PR state, and the two key-named cases
cannot be told apart by refusal reason. What each case does grade is its ``expected``
dict below; the scorer mechanics live in the ``scorers.py`` docstrings.

All scorers are deterministic — no LLM judge — so the suite is cheap to rerun while
iterating on the skill text. ``SandboxedPrivateEval`` runs without a Braintrust key.

**Claude runtime only.** The edit-direction scorer matches Claude's named file tools,
which codex does not carry, so the seeders refuse ``--agent-runtime codex`` as an infra
error (see ``seeders._require_claude_runtime``).

To run:
    flox activate -- bash -c "hogli evals eval_cleanup_stale_flags"
"""

from __future__ import annotations

from products.feature_flags.evals.scorers import (
    EXCLUSION_READ_TOOLS,
    FILE_EDIT_TOOLS,
    FLAG_LOOKUP_TOOLS,
    FLAG_MUTATION_TOOLS,
    FlagStateUnchanged,
    ToolGroupDirection,
)
from products.feature_flags.evals.seeders import (
    STALE_FULL_ROLLOUT_FLAG_KEY,
    STALE_PARTIAL_ROLLOUT_FLAG_KEY,
    guard_claude_runtime,
    seed_stale_full_rollout_flag,
    seed_stale_partial_rollout_flag,
)
from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import NoToolCall
from products.posthog_ai.evals.retrieval.scorers import SkillTriggered

SKILL_NAME = "cleaning-up-stale-feature-flags"
TRIGGER_SCORER_NAME = "cleanup_skill_triggered"
EDIT_SCORER_NAME = "code_edit_direction"
LOOKUP_SCORER_NAME = "flag_lookup_direction"
EXCLUSION_SCORER_NAME = "exclusion_check_direction"

# Shared by the three positive cases; declared once so a direction changed in one
# case but not the others has to be a visible, deliberate edit.
_POSITIVE_EXPECTED = {
    TRIGGER_SCORER_NAME: {"should_load": True},
    EDIT_SCORER_NAME: {"should_edit": False},
    LOOKUP_SCORER_NAME: {"should_look_up": True},
    EXCLUSION_SCORER_NAME: {"should_check_exclusions": True},
}


async def eval_cleanup_stale_flags(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="cleanup_request_executes",
            prompt="Clean up our stale feature flags.",
            setup=seed_stale_full_rollout_flag,
            expected=_POSITIVE_EXPECTED,
            metadata={"trigger": "positive", "skill": SKILL_NAME},
        ),
        SandboxedEvalCase(
            name="unrelated_task_stays_quiet",
            prompt=(
                "We gate new UI in this app behind the 'file-previews' feature flag. "
                "Separate task: shorten this repo's README introduction to at most two "
                "sentences, keeping the meaning."
            ),
            setup=guard_claude_runtime,
            expected={
                TRIGGER_SCORER_NAME: {"should_load": False},
                EDIT_SCORER_NAME: {"should_edit": True},
                LOOKUP_SCORER_NAME: {"should_look_up": False},
                EXCLUSION_SCORER_NAME: {"should_check_exclusions": False},
            },
            metadata={"trigger": "negative", "skill": SKILL_NAME},
        ),
        SandboxedEvalCase(
            name="no_references_is_noop",
            prompt=(
                f"The feature flag '{STALE_FULL_ROLLOUT_FLAG_KEY}' is fully rolled out and "
                "stale. Remove it from this repository."
            ),
            setup=seed_stale_full_rollout_flag,
            expected=_POSITIVE_EXPECTED,
            metadata={"trigger": "positive", "skill": SKILL_NAME, "rollout": "full"},
        ),
        SandboxedEvalCase(
            name="partial_flag_lookup_shape",
            prompt=(
                f"Remove the feature flag '{STALE_PARTIAL_ROLLOUT_FLAG_KEY}' from this "
                "repository and clean up its code."
            ),
            setup=seed_stale_partial_rollout_flag,
            expected=_POSITIVE_EXPECTED,
            metadata={"trigger": "positive", "skill": SKILL_NAME, "rollout": "partial"},
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-feature-flags-cleanup-stale-cli",
        cases=cases,
        scorers=[
            SkillTriggered(SKILL_NAME, name=TRIGGER_SCORER_NAME),
            NoToolCall(FLAG_MUTATION_TOOLS, name="no_flag_mutation"),
            FlagStateUnchanged(),
            ToolGroupDirection(FILE_EDIT_TOOLS, name=EDIT_SCORER_NAME, key="should_edit"),
            ToolGroupDirection(FLAG_LOOKUP_TOOLS, name=LOOKUP_SCORER_NAME, key="should_look_up"),
            ToolGroupDirection(EXCLUSION_READ_TOOLS, name=EXCLUSION_SCORER_NAME, key="should_check_exclusions"),
        ],
        ctx=ctx,
    )
