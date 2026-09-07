"""Baseline trigger evals for the ``instrument-feature-flags`` skill.

The skill is authored in `PostHog/context-mill`, not here — see
``products/feature_flags/skills/README.md`` for the source-of-truth record. This
suite grades whether its description fires on an explicit "put this behind a
feature flag" request and stays quiet on a pure refactor.

**The skill is not in a locally built sandbox, so the suite guards for it.**
``hogli evals`` builds skills through ``LocalSkillsCache.ensure_built()``, which
renders only this repo's ``products/*/skills/`` trees into
``products/posthog_ai/dist/skills/`` and wipes whatever was there. The
context-mill overlay runs in ``.github/workflows/cd-sandbox-base-image.yml``, not
on any local path, so a plain local run has no ``instrument-feature-flags``
installed at all. Without a guard the positive case would score 0 for a missing
skill and the negative case would score 1 for the wrong reason — a suite mean of
0.5 indistinguishable from a real trigger regression. ``require_instrument_skill``
raises instead, which the harness reports as an infra error and excludes from the
score averages.

Two cases share one deterministic scorer — no LLM judge, so the signal is binary
and cheap to rerun while iterating on the skill's description. The scorer grades
each case against the direction it expects, so the suite mean is trigger
accuracy:

* ``explicit_flag_request`` — an explicit "put this behind a feature flag" ask
  about a real surface in the seeded `posthog/hedgebox` checkout. The skill must
  load.
* ``pure_refactor_no_flag`` — a rewrite with no behavior change, the canonical
  non-trigger. The skill must not load.

Prompts describe their target rather than naming a path, because hedgebox is an
external repo cloned at its default branch: a file move there would otherwise
score as a trigger regression here. The trigger wording is what is graded.

The pair is a baseline, not a quality bar: it measures whether the description
fires on the right request, not whether the workflow the skill teaches is good.
Both cases are ``SandboxedPrivateEval`` so they run without a Braintrust key.

**Claude runtime only.** Under ``--agent-runtime codex`` the guard refuses the
cases rather than scoring them. See ``_CODEX_UNSUPPORTED`` for the two reasons and
where each fix belongs.

To run, invoke the command below once. It builds the local skill cache, then the
guard prints the overlay command. Apply that overlay and run the command again: the
second run reuses the cache, so the overlay survives.
    flox activate -- bash -c "hogli evals eval_instrument_flags"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings

from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall
from products.posthog_ai.evals.retrieval.scorers import SkillTriggered
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

SKILL_NAME = "instrument-feature-flags"
SCORER_NAME = "instrument_flags_skill_triggered"

_BUILT_SKILLS_DIR = Path("products/posthog_ai/dist/skills")

_OVERLAY_HINT = f"""\
'{SKILL_NAME}' is not in {_BUILT_SKILLS_DIR}, so the sandbox would run without the
skill this suite grades. It ships from PostHog/context-mill, and only CI overlays it
(.github/workflows/cd-sandbox-base-image.yml). The eval rebuilds the local skill
cache at startup when it is stale or unbuilt, which wipes an overlay applied before
it. The cache is up to date now, so apply the overlay and re-run. Startup then
reuses the cache and the overlay survives:

  curl -fsSL -o /tmp/cm.zip \\
    https://github.com/PostHog/context-mill/releases/latest/download/skills-mcp-resources.zip
  unzip -q -o /tmp/cm.zip -d /tmp/cm
  unzip -q -o /tmp/cm/omnibus-{SKILL_NAME}.zip -d {_BUILT_SKILLS_DIR}/{SKILL_NAME}
  perl -pi -e 's/^(name: *)omnibus-/$1/' {_BUILT_SKILLS_DIR}/{SKILL_NAME}/SKILL.md

Editing any products/*/skills/ file invalidates the cache, so the next run rebuilds
and wipes the overlay again. Re-apply it after that run, not before."""


_CODEX_UNSUPPORTED = f"""\
This suite measures the claude runtime only, so it refuses to run under codex.

Two gaps make a codex run report a number that looks like a trigger result but is not:

1. The local overlay reaches the bind-mounted plugin directory, but codex discovers
   skills from $HOME/.agents/skills, which only install-skills.sh populates when the
   base image is baked. A reused docker image therefore serves stale or missing
   skills while this guard, which stats the host copy, still passes.
2. `RequiredToolCall` matches Edit, Write and MultiEdit. Codex carries no named file
   tools, so `edited_a_file` scores 0 even when the agent edits a file.

Both fixes land outside this product, in sandbox provisioning and in the shared
scorers, and need a live docker plus codex run to validate. Until then, measuring
claude and refusing codex beats reporting a corrupt mean. Run without
`--agent-runtime codex`."""


def require_instrument_skill(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Fail the case as infra error when it cannot be measured in this sandbox.

    A seeder exception is an infra error the harness excludes from score averages,
    which is what both refusals want: no measurement rather than a wrong one.
    """
    if context.runtime_adapter == "codex":
        raise RuntimeError(_CODEX_UNSUPPORTED)

    skill_file = Path(settings.BASE_DIR) / _BUILT_SKILLS_DIR / SKILL_NAME / "SKILL.md"
    if not skill_file.is_file():
        raise RuntimeError(_OVERLAY_HINT)
    return {"skill_source": "context-mill overlay", "skill_file": str(skill_file)}


async def eval_instrument_flags(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="explicit_flag_request",
            prompt=(
                "In this repo, the pricing page marks one of the plans with a "
                "'Most Popular' badge. Put that badge behind a PostHog feature "
                "flag so we can roll it out gradually."
            ),
            setup=require_instrument_skill,
            expected={SCORER_NAME: {"should_load": True}},
            metadata={"trigger": "positive", "skill": SKILL_NAME},
        ),
        SandboxedEvalCase(
            name="pure_refactor_no_flag",
            prompt=(
                "In this repo, the helper that picks a file-type emoji does it "
                "with a chain of if statements. Rewrite it as a lookup table. "
                "Keep the returned emoji for every input the same."
            ),
            setup=require_instrument_skill,
            expected={SCORER_NAME: {"should_load": False}},
            metadata={"trigger": "negative", "skill": SKILL_NAME},
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-feature-flags-instrument-trigger-cli",
        cases=cases,
        scorers=[
            SkillTriggered(SKILL_NAME, name=SCORER_NAME),
            # Both prompts assert something about the cloned checkout. If hedgebox
            # drifts, the agent finds nothing to change and the negative case still
            # scores 1.0 for not loading the skill — a hollow pass. This row drops
            # to 0 instead, so a stale premise is visible rather than silent.
            RequiredToolCall({"Edit", "Write", "MultiEdit"}, name="edited_a_file"),
        ],
        ctx=ctx,
    )
