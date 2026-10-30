"""Is the person unhappy with the PostHog assistant in Slack?

A yes, together with the cheap gates, sends a private invitation to book a research interview.
`no_unasked_invite` is the number to watch: an invitation to a calm person reads as spam. A missed
unhappy message only costs one invitation.

To run:
    hogli evals eval_interview_sentiment
    hogli evals eval_interview_sentiment --eval useless_answer
"""

from __future__ import annotations

import asyncio

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotEval
from products.slack_app.backend.logic import interview_recruitment
from products.slack_app.evals.offline_config import offline_suite
from products.slack_app.evals.scorers import INTERVIEW_SENTIMENT_KEY, InterviewSentimentMatch, NoUnaskedInvite

SUITE_KIND = SuiteKind.ONE_SHOT


def _case(name: str, prompt: str, unhappy: bool) -> BaseEvalCase:
    return BaseEvalCase(name=name, prompt=prompt, expected={INTERVIEW_SENTIMENT_KEY: {"unhappy": unhappy}})


UNHAPPY_CASES = [
    _case("useless_answer", "this is useless, you didn't even look at the right dashboard", True),
    _case("failed_again", "third time asking. the signup count is still wrong. can you actually check it?", True),
    _case("sarcasm", "great, another chart that answers a question I never asked", True),
    _case("angry_caps", "WHY does it keep opening a PR when I only asked a question??", True),
    _case("giving_up", "honestly I'll just write the SQL myself, this bot never gets it right", True),
    _case("slow_complaint", "you took ten minutes to tell me you can't find the event. what's the point", True),
    _case("disappointed", "I expected more, the summary skipped every number I care about", True),
    _case("product_complaint", "PostHog keeps logging me out and now the bot can't see my project either", True),
    _case("non_english", "to je úplně špatně, zase jsi ignoroval ten projekt co jsem napsal", True),
]

NOT_UNHAPPY_CASES = [
    _case("plain_question", "how many people signed up last week?", False),
    _case("terse_instruction", "funnel from pageview to signed_up, last 30 days", False),
    _case("calm_correction", "small thing: I meant the mobile project, not web. can you rerun it?", False),
    _case("thanks", "perfect, that's exactly what I needed, thanks!", False),
    _case("urgent_but_calm", "urgent please, the board meeting is in 20 minutes and I need churn by plan", False),
    # Unhappy, but about their own product or other people, not about the assistant.
    _case("own_product_bug", "our checkout is broken again and customers are furious, find the errors", False),
    _case("annoyed_at_colleague", "ugh, someone deleted the onboarding dashboard. can you rebuild it?", False),
    _case("negative_metric", "retention dropped badly this month, what changed?", False),
]


async def eval_interview_sentiment(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        if task_ctx.demo_data is None:
            return {"unhappy": None, "error": "No demo data team to bill the call to"}
        try:
            verdict = await asyncio.to_thread(
                interview_recruitment.classify_sentiment,
                case.prompt,
                team_id=task_ctx.demo_data.master_team_id,
                distinct_id=None,
                trace_id=None,
            )
        except Exception as error:
            return {"unhappy": None, "error": f"{type(error).__name__}: {error}"}
        # The same rule production applies: an unhappy verdict below the threshold counts as no.
        unhappy = verdict is not None and verdict.is_unhappy
        return {
            "unhappy": unhappy,
            "verdict": {"choice": verdict.choice, "confidence": verdict.confidence} if verdict else None,
            "last_message": f"unhappy={unhappy}",
        }

    await OneShotEval(
        experiment_name="slack-app-interview-sentiment",
        offline_suite=offline_suite(
            "slack_app/eval_interview_sentiment::eval_interview_sentiment",
            metrics=[INTERVIEW_SENTIMENT_KEY, "no_unasked_invite"],
            suite_kind=SUITE_KIND,
        ),
        cases=[*UNHAPPY_CASES, *NOT_UNHAPPY_CASES],
        scorers=[InterviewSentimentMatch(), NoUnaskedInvite()],
        task=task,
        ctx=ctx,
    )
