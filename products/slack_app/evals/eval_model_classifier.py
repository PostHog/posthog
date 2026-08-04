"""Does the model-override classifier read a Slack mention the way a person would?

The unit tests around `classify_slack_app_model_override` feed it canned replies: they
cover parsing, validation, and the catalogue check, and would pass unchanged if the
prompt were replaced with the word "hello". This suite covers the part they can't —
whether the model, reading a real sentence, can tell an instruction about how to run the
task from a task that merely mentions a model.

That distinction is the whole classifier, and it fails asymmetrically: see
`NoUnaskedOverride` in `scorers.py` for why the false-positive rate is the number to
watch rather than overall accuracy.

Public rather than private: the point of the suite is comparing a baseline against a
later prompt or model change, and that history lives in Braintrust keyed on
`experiment_name` — a private run leaves local logs to diff by hand. Every prompt below
is synthetic, so there is no customer text to keep off the wire.

To run:
    hogli evals eval_model_classifier
    hogli evals eval_model_classifier --eval names_model_in_code_change
"""

from __future__ import annotations

import asyncio

from posthog.temporal.ai.slack_app.activities import classifiers

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPublicEval
from products.slack_app.backend.services.model_catalogue import ModelChoice
from products.slack_app.evals.model_classifier_scorers import EXPECTATION_KEY, ModelOverrideMatch, NoUnaskedOverride

SUITE_KIND = SuiteKind.ONE_SHOT

# Frozen rather than `available_model_choices()`: the live catalogue tracks whatever the
# gateway currently serves, so scores would move when a model ships or is retired, for
# reasons that have nothing to do with the prompt. Refresh deliberately, and expect the
# baseline to step when you do.
CHOICES: tuple[ModelChoice, ...] = (
    ModelChoice("claude", "claude-opus-5", "Claude Opus 5", ("low", "medium", "high", "xhigh", "max")),
    ModelChoice("claude", "claude-fable-5", "Claude Fable 5", ("low", "medium", "high", "xhigh", "max")),
    ModelChoice("claude", "claude-sonnet-5", "Claude Sonnet 5", ("low", "medium", "high", "xhigh", "max")),
    ModelChoice("codex", "gpt-5.6-luna", "GPT-5.6 Luna", ("low", "medium", "high", "xhigh", "max")),
    ModelChoice("codex", "gpt-5.6-sol", "GPT-5.6 Sol", ("low", "medium", "high", "xhigh", "max")),
)


def _asks(model: str | None = None, reasoning_effort: str | None = None) -> dict:
    return {EXPECTATION_KEY: {"model": model, "reasoning_effort": reasoning_effort}}


# Deliberately not the prompt's own few-shot examples. Reusing those would measure
# whether the model can copy a list it was just handed, which tells us nothing about the
# sentences people actually send.
INSTRUCTION_CASES = [
    BaseEvalCase(
        name="plain_model_instruction",
        prompt="@PostHog use opus 5 for this — the retention query is returning empty buckets",
        expected=_asks(model="claude-opus-5"),
    ),
    BaseEvalCase(
        name="instruction_after_the_ask",
        prompt="@PostHog can you look into why the billing webhook retries twice? run it on fable please",
        expected=_asks(model="claude-fable-5"),
    ),
    BaseEvalCase(
        name="effort_without_model",
        prompt="@PostHog this one's gnarly, give it max effort — the session replay index is corrupt somehow",
        expected=_asks(reasoning_effort="max"),
    ),
    BaseEvalCase(
        name="model_and_effort",
        prompt="@PostHog run this on sonnet 5 with low effort, it's a one-line copy change in the nav",
        expected=_asks(model="claude-sonnet-5", reasoning_effort="low"),
    ),
    BaseEvalCase(
        name="colloquial_model_name",
        prompt="@PostHog do this one with luna: add a loading state to the cohort picker",
        expected=_asks(model="gpt-5.6-luna"),
    ),
    BaseEvalCase(
        name="instruction_with_model_also_as_subject",
        prompt=(
            "@PostHog use fable for this one. The task: our model picker is missing gpt-5.6-sol, add it to the dropdown"
        ),
        expected=_asks(model="claude-fable-5"),
    ),
]

# The expensive direction. Each of these names a model, and the right answer is to do
# nothing with it.
SUBJECT_MATTER_CASES = [
    BaseEvalCase(
        name="names_model_in_code_change",
        prompt="@PostHog add gpt-5.6-luna to the model picker in settings, it's missing from the dropdown",
        expected=_asks(),
    ),
    BaseEvalCase(
        name="question_comparing_models",
        prompt="@PostHog why is opus 5 slower than sonnet 5 on our eval suite? dig into the traces",
        expected=_asks(),
    ),
    BaseEvalCase(
        name="model_as_incident_topic",
        prompt="@PostHog the fable rollout broke the usage dashboard last night, can you find what changed",
        expected=_asks(),
    ),
    BaseEvalCase(
        name="effort_as_english",
        prompt="@PostHog reasoning about this caching bug is hard, can you take a look at the invalidation logic",
        expected=_asks(),
    ),
    BaseEvalCase(
        name="model_in_config_file",
        prompt="@PostHog our CLASSIFIER_MODEL constant still says claude-haiku-4-5, update it and the tests",
        expected=_asks(),
    ),
    BaseEvalCase(
        name="model_in_error_message",
        prompt='@PostHog users are seeing "model gpt-5.6-sol is not available" on the tasks page, fix the fallback',
        expected=_asks(),
    ),
    BaseEvalCase(
        name="past_tense_report",
        prompt="@PostHog I ran this on opus 5 yesterday and it missed the race condition, try again",
        expected=_asks(),
    ),
    BaseEvalCase(
        name="effort_as_product_copy",
        prompt="@PostHog the effort selector tooltip says 'max effort' but the value sent is xhigh, fix the label",
        expected=_asks(),
    ),
    BaseEvalCase(
        name="no_model_mentioned",
        prompt="@PostHog the checkout funnel drops 40% between steps 2 and 3, can you work out why",
        expected=_asks(),
    ),
]


async def eval_model_classifier(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        # Recorded on every case so an experiment says which model produced its scores —
        # otherwise two runs of the same suite are indistinguishable in the history, which
        # is exactly what you go to the history to compare.
        classifier_model = classifiers.MODEL_OVERRIDE_CLASSIFIER_MODEL
        try:
            # Sync, and blocking on the gateway — keep it off the event loop so cases
            # still run concurrently under the harness's limiter.
            override = await asyncio.to_thread(classifiers.classify_slack_app_model_override, case.prompt, CHOICES)
        except Exception as error:
            return {
                "classifier_model": classifier_model,
                "override": None,
                "error": f"{type(error).__name__}: {error}",
            }
        return {
            "classifier_model": classifier_model,
            "override": override.model_dump() if override else None,
            "last_message": f"{classifier_model}: {override.model_dump() if override else None}",
        }

    await OneShotPublicEval(
        experiment_name="slack-app-model-classifier",
        cases=[*INSTRUCTION_CASES, *SUBJECT_MATTER_CASES],
        scorers=[ModelOverrideMatch(), NoUnaskedOverride()],
        task=task,
        ctx=ctx,
    )
