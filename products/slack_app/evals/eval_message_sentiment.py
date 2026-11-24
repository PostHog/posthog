"""How does the person feel about the PostHog assistant in Slack?

The verdict drives three things: `not_happy` and `frustrated` get a reaction and the interview checks, and
`frustrated` alone can get a calming GIF. `no_unasked_reaction` and `no_unasked_gif` are the numbers to watch,
because a reaction to a calm person reads as spam and a GIF to a mildly unhappy one reads as mockery. A missed
unhappy message only costs one reaction.

The cases cluster on the boundaries the criteria draw: a calm correction against `not_happy`, a question about
an answer against `confused`, `not_happy` against `frustrated`, and bad news about the person's own product
against unhappiness with the assistant.

To run:
    hogli evals eval_message_sentiment
    hogli evals eval_message_sentiment --eval sarcasm
"""

from __future__ import annotations

import asyncio

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotEval
from products.slack_app.backend.logic import message_sentiment
from products.slack_app.backend.logic.message_sentiment import Sentiment
from products.slack_app.evals.offline_config import offline_suite
from products.slack_app.evals.scorers import (
    MESSAGE_SENTIMENT_KEY,
    MessageSentimentMatch,
    NoUnaskedGif,
    NoUnaskedReaction,
    SentimentDetected,
    UnhappyDetected,
)

SUITE_KIND = SuiteKind.ONE_SHOT


def _case(name: str, prompt: str, sentiment: Sentiment) -> BaseEvalCase:
    return BaseEvalCase(name=name, prompt=prompt, expected={MESSAGE_SENTIMENT_KEY: {"sentiment": str(sentiment)}})


HAPPY_CASES = [
    _case("thanks", "perfect, that's exactly what I needed, thanks!", Sentiment.HAPPY),
    _case("praise_with_emoji", "wow, this saved me an hour of digging 🙌", Sentiment.HAPPY),
    _case("relief_after_fix", "nice, the numbers match the dashboard now. finally sorted", Sentiment.HAPPY),
    _case("non_english_thanks", "danke, genau diese Aufschlüsselung habe ich gesucht", Sentiment.HAPPY),
]

NEUTRAL_CASES = [
    _case("plain_question", "how many people signed up last week?", Sentiment.NEUTRAL),
    _case("terse_instruction", "funnel from pageview to signed_up, last 30 days", Sentiment.NEUTRAL),
    _case("calm_correction", "small thing: I meant the mobile project, not web. can you rerun it?", Sentiment.NEUTRAL),
    _case(
        "urgent_but_calm",
        "urgent please, the board meeting is in 20 minutes and I need churn by plan",
        Sentiment.NEUTRAL,
    ),
    _case("polite_follow_up", "thanks. can you also break it down by country?", Sentiment.NEUTRAL),
    _case("one_word", "ok", Sentiment.NEUTRAL),
    # Negative words, but about their own product or other people, not about the assistant.
    _case(
        "own_product_bug", "our checkout is broken again and customers are furious, find the errors", Sentiment.NEUTRAL
    ),
    _case(
        "annoyed_at_colleague", "ugh, someone deleted the onboarding dashboard. can you rebuild it?", Sentiment.NEUTRAL
    ),
    _case("negative_metric", "retention dropped badly this month, what changed?", Sentiment.NEUTRAL),
    _case(
        "pasted_error",
        "getting `ValueError: invalid literal for int()` in our export job, what does it mean?",
        Sentiment.NEUTRAL,
    ),
]

CONFUSED_CASES = [
    _case("number_mismatch", "wait, why is this number different from the one on the dashboard?", Sentiment.CONFUSED),
    _case("which_event", "I don't get it, which event did you count here?", Sentiment.CONFUSED),
    _case("lost_on_interval", "hm, I'm lost. is this weekly or monthly?", Sentiment.CONFUSED),
    _case("term_meaning", "what does 'unique users' mean in this chart exactly?", Sentiment.CONFUSED),
    _case("non_english_confused", "nerozumím, co znamená ten druhý sloupec?", Sentiment.CONFUSED),
]

NOT_HAPPY_CASES = [
    _case("disappointed", "I expected more, the summary skipped every number I care about", Sentiment.NOT_HAPPY),
    _case("wrong_metric", "that's not what I asked for, I wanted signups, not pageviews", Sentiment.NOT_HAPPY),
    _case("hard_to_read", "meh, the chart is hard to read and the labels are cut off", Sentiment.NOT_HAPPY),
    _case("doubts_answer", "this doesn't look right to me, the trend should be going up", Sentiment.NOT_HAPPY),
    _case(
        "product_complaint",
        "PostHog keeps logging me out and now the bot can't see my project either",
        Sentiment.NOT_HAPPY,
    ),
    _case("polite_complaint", "thanks for trying, but this misses the point of my question", Sentiment.NOT_HAPPY),
]

FRUSTRATED_CASES = [
    _case("useless_answer", "this is useless, you didn't even look at the right dashboard", Sentiment.FRUSTRATED),
    _case(
        "failed_again",
        "third time asking. the signup count is still wrong. can you actually check it?",
        Sentiment.FRUSTRATED,
    ),
    _case("sarcasm", "great, another chart that answers a question I never asked", Sentiment.FRUSTRATED),
    _case("angry_caps", "WHY does it keep opening a PR when I only asked a question??", Sentiment.FRUSTRATED),
    _case("giving_up", "honestly I'll just write the SQL myself, this bot never gets it right", Sentiment.FRUSTRATED),
    _case(
        "slow_complaint",
        "you took ten minutes to tell me you can't find the event. what's the point",
        Sentiment.FRUSTRATED,
    ),
    _case(
        "non_english_frustrated",
        "to je úplně špatně, zase jsi ignoroval ten projekt co jsem napsal",
        Sentiment.FRUSTRATED,
    ),
]


async def eval_message_sentiment(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        if task_ctx.demo_data is None:
            return {"sentiment": None, "error": "No demo data team to bill the call to"}
        try:
            verdict = await asyncio.to_thread(
                message_sentiment.classify_sentiment,
                case.prompt,
                team_id=task_ctx.demo_data.master_team_id,
                distinct_id=None,
                trace_id=None,
            )
        except Exception as error:
            return {"sentiment": None, "error": f"{type(error).__name__}: {error}"}
        if verdict is None:
            return {"sentiment": None, "error": "The model gave no choice"}
        # The state production acts on, after the confidence rule, not the model's raw pick.
        sentiment = str(verdict.sentiment)
        return {
            "sentiment": sentiment,
            "verdict": {
                "choice": verdict.choice,
                "confidence": verdict.confidence,
                "probabilities": dict(verdict.probabilities),
            },
            "last_message": f"sentiment={sentiment}",
        }

    await OneShotEval(
        experiment_name="slack-app-message-sentiment",
        offline_suite=offline_suite(
            "slack_app/eval_message_sentiment::eval_message_sentiment",
            metrics=[
                MESSAGE_SENTIMENT_KEY,
                *(f"{sentiment}_detected" for sentiment in Sentiment),
                "unhappy_detected",
                "no_unasked_reaction",
                "no_unasked_gif",
            ],
            suite_kind=SUITE_KIND,
        ),
        cases=[*HAPPY_CASES, *NEUTRAL_CASES, *CONFUSED_CASES, *NOT_HAPPY_CASES, *FRUSTRATED_CASES],
        scorers=[
            MessageSentimentMatch(),
            *(SentimentDetected(str(sentiment)) for sentiment in Sentiment),
            UnhappyDetected(),
            NoUnaskedReaction(),
            NoUnaskedGif(),
        ],
        task=task,
        ctx=ctx,
    )
