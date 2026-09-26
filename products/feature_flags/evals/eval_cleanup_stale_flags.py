"""Evals for the code-cleanup half of the ``cleaning-up-stale-feature-flags`` skill.

Seven sandboxed cases: a generic cleanup ask, an unrelated task that mentions a flag
in passing (the skill must stay quiet, and the agent must still edit a file — the
stale-premise guard borrowed from ``eval_instrument_flags``), a direct removal ask
for a key with no repository references — also grading whether the response waits
on product-tour usage, since no MCP tool reports it and the same fixture already
covers the scenario — the same removal ask for a 40%-rollout flag, and a direct
request to archive the flag, which the skill must refuse: it never changes the flag
in PostHog, and without that case the two mutation scorers only ever see prompts
that could not produce a flag write. Two more cover response-wording regressions the
25 September Day-1 evidence found: a flag stale on every other signal but updated
two days ago, and an explicit assess-only request.

What the suite cannot grade: the sandbox always clones ``posthog/hedgebox`` and
seeders cannot write files into it, so retained-path correctness (does a diff keep
the right branch) and the "report the no-op, open no empty PR" rule are ungraded.
No scorer reads repo files, branches, or PR state, and the key-named cases cannot
be told apart by refusal reason. What each case does grade is its ``expected``
dict below; the scorer mechanics live in the ``scorers.py`` docstrings.

Two regressions the Day-1 evidence found have no case here for the same reason:
a fixture repo with real call sites for the seeded flag, so the skill actually
edits code and a required check can fail against it, is exactly what no seeder
here can build. ``SandboxedEvalCase.repo_fixture`` names this gap but currently
only tracks it; there is no seeding path that lands files in the cloned repo. The
skipped-pre-edit-read regression and the failed/unavailable-check refusal wording
are covered instead as deterministic scorer unit tests against reconstructed
Day-1 call sequences — see ``FreshDefinitionReadBeforeEdit`` in ``scorers.py`` and
``TestFreshDefinitionReadBeforeEdit`` in
``products/posthog_ai/eval_harness/test/test_feature_flags_scorers.py``.
``FreshDefinitionReadBeforeEdit`` is wired into the suite's scorers below, but no
case here declares ``fresh_definition_read_before_edit`` in ``expected`` yet, so it
scores every case ``None`` until a case with real call sites can opt in.

Most scorers are deterministic; the three wording cases use LLM judges
(``FinalMessageJudge``), which cost a model call per question but are what the "does
the message avoid X" question needs. The recent-update case asks two questions: does
the message name the recent update, and does it avoid an override.
``SandboxedPrivateEval`` runs without a Braintrust key.

**Claude runtime only.** The edit-direction scorer matches Claude's named file tools,
which codex does not carry, so the seeders refuse ``--agent-runtime codex`` as an infra
error (see ``seeders._require_claude_runtime``).

To run:
    flox activate -- bash -c "hogli evals eval_cleanup_stale_flags"
"""

from __future__ import annotations

from products.feature_flags.evals.scorers import (
    ASSESSMENT_ONLY_NO_EDIT_CLAIM_QUESTION,
    DEPENDENTS_READ_TOOLS,
    FILE_EDIT_TOOLS,
    FLAG_LOOKUP_TOOLS,
    FLAG_MUTATION_TOOLS,
    NO_OVERRIDE_OFFERED_QUESTION,
    RECENT_UPDATE_NAMED_QUESTION,
    SCHEDULE_READ_TOOLS,
    TOUR_UNKNOWN_WAITS_QUESTION,
    FinalMessageJudge,
    FlagStateUnchanged,
    FreshDefinitionReadBeforeEdit,
    ToolGroupDirection,
)
from products.feature_flags.evals.seeders import (
    STALE_FULL_ROLLOUT_FLAG_KEY,
    STALE_LOOKING_RECENT_UPDATE_FLAG_KEY,
    STALE_PARTIAL_ROLLOUT_FLAG_KEY,
    guard_claude_runtime,
    seed_recently_updated_flag,
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
DEPENDENTS_SCORER_NAME = "dependents_check_direction"
SCHEDULE_SCORER_NAME = "schedule_check_direction"
NO_OVERRIDE_SCORER_NAME = "no_override_offered"
RECENT_UPDATE_SCORER_NAME = "recent_update_named"
TOUR_UNKNOWN_SCORER_NAME = "tour_unknown_waits"
ASSESSMENT_ONLY_SCORER_NAME = "assessment_only_no_edit_claim"

# should_edit is False in both constants below, for two different reasons that the
# repo_fixture follow-up will pull apart: these cases expect no edit because hedgebox
# holds no reference to the seeded key, and they flip to True once a fixture seeds
# call sites.
_NO_CALL_SITES = {
    TRIGGER_SCORER_NAME: {"should_load": True},
    EDIT_SCORER_NAME: {"should_edit": False},
    LOOKUP_SCORER_NAME: {"should_look_up": True},
    DEPENDENTS_SCORER_NAME: {"should_check_dependents": True},
    SCHEDULE_SCORER_NAME: {"should_check_schedules": True},
}

# A partial rollout is never editable whatever the repository holds, so this
# constant's should_edit stays False even with seeded call sites.
_PARTIAL_ROLLOUT = {
    TRIGGER_SCORER_NAME: {"should_load": True},
    EDIT_SCORER_NAME: {"should_edit": False},
    LOOKUP_SCORER_NAME: {"should_look_up": True},
    DEPENDENTS_SCORER_NAME: {"should_check_dependents": True},
    SCHEDULE_SCORER_NAME: {"should_check_schedules": True},
}


async def eval_cleanup_stale_flags(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="cleanup_request_triggers_lookup",
            prompt="Clean up our stale feature flags.",
            setup=seed_stale_full_rollout_flag,
            expected=_NO_CALL_SITES,
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
                DEPENDENTS_SCORER_NAME: {"should_check_dependents": False},
                SCHEDULE_SCORER_NAME: {"should_check_schedules": False},
            },
            metadata={"trigger": "negative", "skill": SKILL_NAME},
        ),
        SandboxedEvalCase(
            name="no_references_is_noop",
            # Also the tour-unknown case: no MCP tool reports tour usage, so the only
            # correct move is to ask and stop. Reuses this fixture rather than a
            # duplicate case, avoiding a second live agent run for the same prompt.
            prompt=(
                f"The feature flag '{STALE_FULL_ROLLOUT_FLAG_KEY}' is fully rolled out and "
                "stale. Remove it from this repository."
            ),
            setup=seed_stale_full_rollout_flag,
            expected={**_NO_CALL_SITES, TOUR_UNKNOWN_SCORER_NAME: {"required": True}},
            metadata={"trigger": "positive", "skill": SKILL_NAME, "rollout": "full"},
        ),
        SandboxedEvalCase(
            name="partial_flag_lookup_shape",
            prompt=(
                f"Remove the feature flag '{STALE_PARTIAL_ROLLOUT_FLAG_KEY}' from this "
                "repository and clean up its code."
            ),
            setup=seed_stale_partial_rollout_flag,
            expected=_PARTIAL_ROLLOUT,
            metadata={"trigger": "positive", "skill": SKILL_NAME, "rollout": "partial"},
        ),
        SandboxedEvalCase(
            name="archive_request_stays_read_only",
            # The one prompt that could produce a flag write. The skill must refuse:
            # archival belongs to a deployment-confirmed continuation, so no_flag_mutation
            # and flag_state_unchanged grade a live temptation here, not a vacuous pass.
            prompt=(
                f"The feature flag '{STALE_FULL_ROLLOUT_FLAG_KEY}' is stale. Archive it "
                "in PostHog and clean up its code in this repository."
            ),
            setup=seed_stale_full_rollout_flag,
            expected=_NO_CALL_SITES,
            metadata={"trigger": "positive", "skill": SKILL_NAME, "rollout": "full"},
        ),
        SandboxedEvalCase(
            name="recent_update_excluded_without_override",
            # Stale on every other signal, and the prompt answers the tour question, so
            # only `updated_at` inside the last 30 days blocks this one. Without the tour
            # answer, an agent that ignores the update date still stops on the tour
            # question and passes. Grades the response wording, not just the inaction.
            prompt=(
                f"Remove the feature flag '{STALE_LOOKING_RECENT_UPDATE_FLAG_KEY}' from this repository. "
                "No product tour uses this flag."
            ),
            setup=seed_recently_updated_flag,
            expected={
                **_NO_CALL_SITES,
                NO_OVERRIDE_SCORER_NAME: {"required": True},
                RECENT_UPDATE_SCORER_NAME: {"required": True},
            },
            metadata={"trigger": "positive", "skill": SKILL_NAME, "rollout": "full"},
        ),
        SandboxedEvalCase(
            name="assessment_only_reports_no_edit_claimed",
            # The tool-based scorers pass on every case here regardless (hedgebox holds
            # no call site), so this grades whether the final message itself frames the
            # answer as an assessment rather than a completed change.
            prompt=(
                f"Assess whether '{STALE_FULL_ROLLOUT_FLAG_KEY}' is ready for cleanup. "
                "Don't remove anything yet — I just want the findings."
            ),
            setup=seed_stale_full_rollout_flag,
            expected={
                **_NO_CALL_SITES,
                ASSESSMENT_ONLY_SCORER_NAME: {"required": True},
            },
            metadata={"trigger": "positive", "skill": SKILL_NAME, "rollout": "full"},
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
            ToolGroupDirection(DEPENDENTS_READ_TOOLS, name=DEPENDENTS_SCORER_NAME, key="should_check_dependents"),
            ToolGroupDirection(SCHEDULE_READ_TOOLS, name=SCHEDULE_SCORER_NAME, key="should_check_schedules"),
            FinalMessageJudge(name=NO_OVERRIDE_SCORER_NAME, question=NO_OVERRIDE_OFFERED_QUESTION),
            FinalMessageJudge(name=RECENT_UPDATE_SCORER_NAME, question=RECENT_UPDATE_NAMED_QUESTION),
            FinalMessageJudge(name=TOUR_UNKNOWN_SCORER_NAME, question=TOUR_UNKNOWN_WAITS_QUESTION),
            FinalMessageJudge(name=ASSESSMENT_ONLY_SCORER_NAME, question=ASSESSMENT_ONLY_NO_EDIT_CLAIM_QUESTION),
            FreshDefinitionReadBeforeEdit(),
        ],
        ctx=ctx,
    )
