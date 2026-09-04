"""Phase A evals for the ``cleaning-up-stale-feature-flags`` skill.

Four cases grade the parts of the repository-cleanup workflow the sandbox can measure
deterministically. The sandbox always clones ``posthog/hedgebox``, and seeders cannot
write files into it, so retained-path correctness (does the diff keep the right branch)
is not coverable here without depending on specific flag-key usages in an external repo
that can drift. What is coverable, with invented flag keys seeded into the case team:

* ``cleanup_request_executes`` — a generic "clean up our stale flags" ask. The skill must
  load, and because the seeded key appears nowhere in hedgebox, a correct run ends in a
  reported no-op: no code edits and no flag mutation.
* ``unrelated_task_stays_quiet`` — an ordinary edit task that mentions a flag in passing.
  The skill must not load, and the agent must still edit a file (the stale-premise guard
  borrowed from ``eval_instrument_flags``) without touching any flag.
* ``no_references_is_noop`` — a direct "remove this flag from the repo" ask for a key with
  zero references. The skill's no-op rule: report, no edits, no empty PR, no mutation.
* ``partial_flag_untouched`` — a direct removal ask for a 40%-rollout flag. The skill's
  partial rule: explain the decision, change nothing.

Every case shares ``NoToolCall`` over the flag lifecycle verbs — Phase A of the skill
never mutates a flag, whatever else happens. Edit direction is graded by the suite-local
``CodeEditDirection``, which reads ``expected[<name>]["should_edit"]`` the way
``SkillTriggered`` reads ``should_load``, so one scorer list spans positive and negative
cases without half the scorecard self-skipping.

All scorers are deterministic — no LLM judge — so the suite is cheap to rerun while
iterating on the skill text. ``SandboxedPrivateEval`` runs without a Braintrust key.

**Claude runtime only.** ``CodeEditDirection`` matches Claude's named file tools, which
codex does not carry, so the seeders refuse ``--agent-runtime codex`` as an infra error
(see ``seeders._require_claude_runtime``).

To run:
    flox activate -- bash -c "hogli evals eval_cleanup_stale_flags"
"""

from __future__ import annotations

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
from products.posthog_ai.eval_harness.log_parser import LogParser
from products.posthog_ai.eval_harness.scorers import NoToolCall
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.posthog_ai.evals.retrieval.scorers import SkillTriggered

SKILL_NAME = "cleaning-up-stale-feature-flags"
TRIGGER_SCORER_NAME = "cleanup_skill_triggered"
EDIT_SCORER_NAME = "code_edit_direction"

# Every write verb the current MCP surface offers for a flag. Phase A of the skill must
# not call any of them on any case — archival belongs to a deployment-confirmed
# continuation, and nothing in these prompts confirms a deployment.
FLAG_MUTATION_TOOLS = frozenset(
    {
        "feature-flag-archive",
        "feature-flag-unarchive",
        "feature-flag-disable",
        "feature-flag-enable",
        "delete-feature-flag",
        "update-feature-flag",
        "create-feature-flag",
    }
)

_FILE_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit"})


class CodeEditDirection(Scorer):
    """Binary: did the agent's file editing match the direction the case expects?

    ``expected[<name>] = {"should_edit": <bool>}`` on every case; an undeclared direction
    skips rather than assuming one. Counts only successful named file-tool calls, so a
    failed edit attempt doesn't flip a no-edit case.
    """

    def _name(self) -> str:
        return EDIT_SCORER_NAME

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        if not output or not output.get("raw_log"):
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        direction = (expected or {}).get(self._name())
        if not isinstance(direction, dict) or "should_edit" not in direction:
            return Score(name=self._name(), score=None, metadata={"reason": "No should_edit declared"})

        parser = LogParser.cached(output["raw_log"], initial_prompt=output.get("prompt", "") or "")
        edits = [call.name for call in parser.get_tool_calls() if not call.is_error and call.name in _FILE_EDIT_TOOLS]
        should_edit = bool(direction["should_edit"])
        matched = bool(edits) == should_edit
        return Score(
            name=self._name(),
            score=1.0 if matched else 0.0,
            metadata={"should_edit": should_edit, "edit_calls": edits[:10]},
        )


async def eval_cleanup_stale_flags(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="cleanup_request_executes",
            prompt="Clean up our stale feature flags.",
            setup=seed_stale_full_rollout_flag,
            expected={
                TRIGGER_SCORER_NAME: {"should_load": True},
                EDIT_SCORER_NAME: {"should_edit": False},
            },
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
            expected={
                TRIGGER_SCORER_NAME: {"should_load": True},
                EDIT_SCORER_NAME: {"should_edit": False},
            },
            metadata={"trigger": "positive", "skill": SKILL_NAME, "rollout": "full"},
        ),
        SandboxedEvalCase(
            name="partial_flag_untouched",
            prompt=(
                f"Remove the feature flag '{STALE_PARTIAL_ROLLOUT_FLAG_KEY}' from this "
                "repository and clean up its code."
            ),
            setup=seed_stale_partial_rollout_flag,
            expected={
                TRIGGER_SCORER_NAME: {"should_load": True},
                EDIT_SCORER_NAME: {"should_edit": False},
            },
            metadata={"trigger": "positive", "skill": SKILL_NAME, "rollout": "partial"},
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-feature-flags-cleanup-stale-cli",
        cases=cases,
        scorers=[
            SkillTriggered(SKILL_NAME, name=TRIGGER_SCORER_NAME),
            NoToolCall(FLAG_MUTATION_TOOLS, name="no_flag_mutation"),
            CodeEditDirection(),
        ],
        ctx=ctx,
    )
