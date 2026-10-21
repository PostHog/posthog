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

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPublicEval
from products.slack_app.backend.temporal.activities import untagged_question
from products.slack_app.evals.offline_config import offline_suite
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
    # A metric written as its acronym is the same data question as the metric spelled out.
    BaseEvalCase(
        name="metric_acronym_with_greeting",
        prompt="Hey posthog, what's the DAU for last week?",
        expected=_answerable(True),
    ),
    BaseEvalCase(
        name="metric_acronym_trend",
        prompt="is MAU up or down vs the month before?",
        expected=_answerable(True),
    ),
    # One case per kind of data the assistant can read, beyond the trends and errors above.
    BaseEvalCase(
        name="cohort_retention",
        prompt="what does week 4 retention look like for people who signed up in March?",
        expected=_answerable(True),
    ),
    BaseEvalCase(
        name="session_recordings",
        prompt="can we find recordings of users who rage-clicked the export button?",
        expected=_answerable(True),
    ),
    BaseEvalCase(
        name="experiment_result",
        prompt="did the pricing page experiment reach significance yet?",
        expected=_answerable(True),
    ),
    BaseEvalCase(
        name="survey_answers",
        prompt="what did people say in the NPS survey this month?",
        expected=_answerable(True),
    ),
    BaseEvalCase(
        name="llm_cost",
        prompt="how much did our LLM calls cost yesterday?",
        expected=_answerable(True),
    ),
    BaseEvalCase(
        name="product_how_to",
        prompt="how do I filter out internal users from my insights in PostHog?",
        expected=_answerable(True),
    ),
    BaseEvalCase(
        name="event_in_the_code",
        prompt="where in our code do we fire the checkout_started event?",
        expected=_answerable(True),
    ),
    BaseEvalCase(
        name="error_spike_cause",
        prompt="why did the TypeError on the dashboard page spike overnight?",
        expected=_answerable(True),
    ),
    BaseEvalCase(
        name="churn_after_change",
        prompt="has churn gone up since we shortened the free trial?",
        expected=_answerable(True),
    ),
    BaseEvalCase(
        name="question_in_czech",
        prompt="kolik lidí se včera zaregistrovalo?",
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
    # Acronyms that are not product metrics, so the shorthand rule must not reach them.
    BaseEvalCase(
        name="acronym_that_is_not_a_metric",
        prompt="anyone know the ETA on the new laptops?",
        expected=_answerable(False),
    ),
    BaseEvalCase(
        name="hr_acronym",
        prompt="what's our PTO policy over the holidays?",
        expected=_answerable(False),
    ),
    # A metric named in a question that asks for an opinion, not for the number.
    BaseEvalCase(
        name="metric_in_an_opinion_question",
        prompt="should we use DAU or WAU as our north star metric?",
        expected=_answerable(False),
    ),
    BaseEvalCase(
        name="strategy_question",
        prompt="should we prioritize mobile or web next quarter?",
        expected=_answerable(False),
    ),
    BaseEvalCase(
        name="finance_question",
        prompt="what's our burn rate looking like this quarter?",
        expected=_answerable(False),
    ),
    BaseEvalCase(
        name="sales_deal",
        prompt="has the Northwind deal closed yet?",
        expected=_answerable(False),
    ),
    BaseEvalCase(
        name="it_outage",
        prompt="is the VPN down for anyone else?",
        expected=_answerable(False),
    ),
    BaseEvalCase(
        name="too_vague",
        prompt="any thoughts on this one?",
        expected=_answerable(False),
    ),
    BaseEvalCase(
        name="personal_favor",
        prompt="can someone grab me a coffee on the way in?",
        expected=_answerable(False),
    ),
    BaseEvalCase(
        name="question_for_a_named_person",
        prompt="Sam, what did you think of the demo yesterday?",
        expected=_answerable(False),
    ),
    BaseEvalCase(
        name="document_status",
        prompt="is the Q3 roadmap doc ready for review?",
        expected=_answerable(False),
    ),
    BaseEvalCase(
        name="hiring_question",
        prompt="how many open roles do we have on the growth team?",
        expected=_answerable(False),
    ),
    BaseEvalCase(
        name="company_calendar",
        prompt="when is the next company holiday?",
        expected=_answerable(False),
    ),
    BaseEvalCase(
        name="outside_world",
        prompt="what's the weather going to be like in London tomorrow?",
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
        offline_suite=offline_suite(
            "slack_app/eval_untagged_question::eval_untagged_question",
            metrics=[UNTAGGED_QUESTION_KEY, "no_unasked_answer"],
            suite_kind=SUITE_KIND,
        ),
        cases=[*ANSWERABLE_CASES, *LEAVE_ALONE_CASES],
        scorers=[UntaggedQuestionMatch(), NoUnaskedAnswer()],
        task=task,
        ctx=ctx,
    )
