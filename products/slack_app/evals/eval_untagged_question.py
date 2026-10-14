"""Which top-level channel messages, posted without tagging the app, can PostHog answer?

Every top-level message in a channel the app is in that looks like a question reaches
`classify_untagged_question`, which asks Jev, a System One decision model, two yes/no
questions. Both must clear `UNTAGGED_QUESTION_MIN_PROBABILITY`.

Nobody asked PostHog anything, so `no_unasked_answer` is the number to watch: a wrong answer
interrupts a conversation in public. A missed question costs the author one @PostHog.

To run:
    hogli evals eval_untagged_question
    hogli evals eval_untagged_question --eval signups_last_week
"""

from __future__ import annotations

import asyncio

from posthog.temporal.ai.slack_app.activities import untagged_question

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPublicEval
from products.slack_app.evals.scorers import UNTAGGED_QUESTION_KEY, NoUnaskedAnswer, UntaggedQuestionMatch

SUITE_KIND = SuiteKind.ONE_SHOT


def _answerable(answerable: bool) -> dict:
    return {UNTAGGED_QUESTION_KEY: {"answerable": answerable}}


ANSWERABLE_CASES = [
    BaseEvalCase(name="signups_last_week", prompt="how many people signed up last week?", expected=_answerable(True)),
    BaseEvalCase(
        name="funnel_drop",
        prompt="Why did conversion from signup to first upload drop so much yesterday?",
        expected=_answerable(True),
    ),
    BaseEvalCase(
        name="flag_rollout_state",
        prompt="is the new onboarding flag rolled out to everyone yet or still 50%?",
        expected=_answerable(True),
    ),
    BaseEvalCase(
        name="errors_since_deploy",
        prompt="Are we seeing more errors on the file upload page since this morning's deploy?",
        expected=_answerable(True),
    ),
    BaseEvalCase(
        name="feature_adoption",
        prompt="what share of weekly active users actually used shared folders this month?",
        expected=_answerable(True),
    ),
]

# Messages that look like questions, so they pass the webhook's cheap gate, and that PostHog
# must leave alone.
LEAVE_ALONE_CASES = [
    BaseEvalCase(name="lunch_plan", prompt="lunch at 12:30 today?", expected=_answerable(False)),
    BaseEvalCase(name="who_is_on_call", prompt="who's on call this weekend?", expected=_answerable(False)),
    BaseEvalCase(
        name="meeting_time", prompt="should we move standup to 10am from next week?", expected=_answerable(False)
    ),
    BaseEvalCase(
        name="colleague_availability",
        prompt="does anyone know when Priya is back from leave?",
        expected=_answerable(False),
    ),
    BaseEvalCase(name="opinion_poll", prompt="what do you all think of the new logo?", expected=_answerable(False)),
    BaseEvalCase(
        name="request_for_a_person",
        prompt="can someone review my PR when you have a minute?",
        expected=_answerable(False),
    ),
    BaseEvalCase(name="small_talk", prompt="how's everyone doing after the offsite?", expected=_answerable(False)),
    BaseEvalCase(
        name="contract_question",
        prompt="when does our contract with the payments vendor renew?",
        expected=_answerable(False),
    ),
    BaseEvalCase(
        name="rhetorical",
        prompt="Why is it always the Friday deploys that break? Anyway, fixed now.",
        expected=_answerable(False),
    ),
    BaseEvalCase(
        name="announcement_with_question",
        prompt="Shipped the new pricing page today! Any feedback, drop it in the thread?",
        expected=_answerable(False),
    ),
]


async def eval_untagged_question(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        model = untagged_question.UNTAGGED_QUESTION_DECISION_MODEL
        if task_ctx.demo_data is None:
            return {"decision_model": model, "answerable": None, "error": "No demo data team to bill the call to"}
        try:
            # Sync and blocking on the gateway, so off the event loop.
            verdict = await asyncio.to_thread(
                untagged_question.classify_untagged_question,
                case.prompt,
                team_id=task_ctx.demo_data.master_team_id,
                distinct_id=None,
            )
        except Exception as error:
            return {"decision_model": model, "answerable": None, "error": f"{type(error).__name__}: {error}"}
        answerable = verdict is not None and verdict.answerable
        return {
            "decision_model": model,
            "answerable": answerable,
            "verdict": {
                "asks_for_information": verdict.asks_for_information,
                "answerable_by_posthog": verdict.answerable_by_posthog,
            }
            if verdict
            else None,
            "last_message": f"{model}: answerable={answerable}",
        }

    await OneShotPublicEval(
        experiment_name="slack-app-untagged-question",
        cases=[*ANSWERABLE_CASES, *LEAVE_ALONE_CASES],
        scorers=[UntaggedQuestionMatch(), NoUnaskedAnswer()],
        task=task,
        ctx=ctx,
    )
