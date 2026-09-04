"""Phase A evals for the ``cleaning-up-stale-feature-flags`` skill.

Four cases grade the parts of the repository-cleanup workflow the sandbox can measure
deterministically. The sandbox always clones ``posthog/hedgebox``, and seeders cannot
write files into it, so retained-path correctness (does the diff keep the right branch)
is not coverable here without depending on specific flag-key usages in an external repo
that can drift. What is coverable, with invented flag keys seeded into the case team:

* ``cleanup_request_executes`` — a generic "clean up our stale flags" ask. The skill must
  load, the agent must look the seeded flag up in PostHog, and because the seeded key
  appears nowhere in hedgebox, a correct run ends with no code edits and no flag mutation.
* ``unrelated_task_stays_quiet`` — an ordinary edit task that mentions a flag in passing.
  The skill must not load, no flag read tool may be called, and the agent must still edit
  a file (the stale-premise guard borrowed from ``eval_instrument_flags``).
* ``no_references_is_noop`` — a direct "remove this flag from the repo" ask for a key with
  zero references. Graded: skill load, flag lookup, no edits, no mutation. The "report the
  no-op, open no empty PR" half of the rule is not graded; no scorer reads branch, commit,
  or PR state.
* ``partial_flag_untouched`` — a direct removal ask for a 40%-rollout flag. Graded the
  same way as ``no_references_is_noop``: the scorers cannot tell a partial-rule refusal
  from a no-references no-op, because hedgebox has no flag call sites either way. The case
  earns its keep by feeding the partial-rollout shape through the lookup.

Every case shares ``NoToolCall`` over the flag write verbs — Phase A of the skill never
mutates a flag, whatever else happens. Direction over a tool group is graded by
``scorers.ToolGroupDirection``, which reads ``expected[<name>][<key>]`` the way
``SkillTriggered`` reads ``should_load``: one instance over Claude's file-edit tools
(``should_edit``) and one over the flag read tools (``should_look_up``), so one scorer
list spans positive and negative cases without half the scorecard self-skipping, and a
run that loads the skill and then never contacts PostHog fails the positive cases.

All scorers are deterministic — no LLM judge — so the suite is cheap to rerun while
iterating on the skill text. ``SandboxedPrivateEval`` runs without a Braintrust key.

**Claude runtime only.** The edit-direction scorer matches Claude's named file tools,
which codex does not carry, so the seeders refuse ``--agent-runtime codex`` as an infra
error (see ``seeders._require_claude_runtime``).

To run:
    flox activate -- bash -c "hogli evals eval_cleanup_stale_flags"
"""

from __future__ import annotations

from products.feature_flags.evals.scorers import FILE_EDIT_TOOLS, FLAG_LOOKUP_TOOLS, ToolGroupDirection
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
        "feature-flags-bulk-delete-create",
        "feature-flags-bulk-update-tags-create",
        "feature-flags-copy-flags-create",
        "scheduled-changes-create",
        "scheduled-changes-update",
        "scheduled-changes-delete",
    }
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
                LOOKUP_SCORER_NAME: {"should_look_up": True},
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
                LOOKUP_SCORER_NAME: {"should_look_up": False},
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
                LOOKUP_SCORER_NAME: {"should_look_up": True},
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
                LOOKUP_SCORER_NAME: {"should_look_up": True},
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
            ToolGroupDirection(FILE_EDIT_TOOLS, name=EDIT_SCORER_NAME, key="should_edit"),
            ToolGroupDirection(FLAG_LOOKUP_TOOLS, name=LOOKUP_SCORER_NAME, key="should_look_up"),
        ],
        ctx=ctx,
    )
