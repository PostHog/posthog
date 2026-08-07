"""In a thread the agent is working in, which untagged replies are instructions to it?

Once the Slack App picks up a task, people stop tagging it. They just talk: about the
work, about the product, about the agent, and occasionally to it. Every reply hits
`classify_message_is_agent_directed`, which decides whether the agent wakes up.

The unit tests around it cover the emoji heuristic and the error path with canned replies,
and would pass with the prompt replaced by "hello". What they cannot cover is the
judgement call: whether "this needs a stronger label" is an instruction or two people
agreeing with each other.

The errors are not symmetric, which is why `no_unasked_wake` is the number to watch rather
than accuracy. A missed instruction costs the author one `@PostHog` — the same thing they
would have typed anyway. A wrong wake-up puts the agent into a conversation it was not part
of, in public, where everyone in the thread sees it interject.

The chatter cases are the point of the suite, and most of them are drawn from threads where
the classifier woke on messages nobody had addressed to it: opinions about the work,
questions about the bot's own behaviour, people replying to each other. Several are
decidable only from the preceding messages, which is why cases carry a thread.

To run:
    hogli evals eval_followup_classifier
    hogli evals eval_followup_classifier --eval opinion_about_the_product
"""

from __future__ import annotations

import asyncio

from posthog.temporal.ai.slack_app.activities import classifiers

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPublicEval
from products.slack_app.evals.scorers import FOLLOWUP_KEY, FollowupRoutingMatch, NoUnaskedWake, require_llm_gateway

SUITE_KIND = SuiteKind.ONE_SHOT

TASK_TITLE = "Fix the checkout button not firing autocapture events"

# The thread every case continues: a human asked, the agent acknowledged. Cases add the
# one reply under test on top of it.
THREAD = [
    {"user": "alice", "text": "@PostHog autocapture isn't picking up clicks on our checkout button", "ts": "1.0"},
    {"user": "posthog", "text": "Looking into it — checking how the button is rendered.", "ts": "2.0"},
]


def _routes(agent_directed: bool) -> dict:
    return {FOLLOWUP_KEY: {"agent_directed": agent_directed}}


# Instructions to the agent. Only the first addresses it by name; the rest are the shapes
# people actually use once they have stopped tagging.
DIRECTED_CASES = [
    BaseEvalCase(
        name="direct_instruction",
        prompt="@PostHog also check the mobile breakpoint while you're in there",
        expected=_routes(True),
    ),
    BaseEvalCase(
        name="scope_correction",
        prompt="actually skip the analytics wrapper, just fix the button handler",
        expected=_routes(True),
    ),
    BaseEvalCase(
        name="question_about_the_work",
        prompt="why did you skip the redesign commit? that's when it broke",
        expected=_routes(True),
    ),
    BaseEvalCase(
        name="order_to_retry",
        prompt="try again, this time start from the checkout component instead",
        expected=_routes(True),
    ),
    BaseEvalCase(
        name="correction_of_the_agent",
        prompt="no, the bug is in the handler, not the debounce wrapper — look there",
        expected=_routes(True),
    ),
    BaseEvalCase(
        name="follow_up_ask",
        prompt="can you open a PR for the mobile breakpoint too once that's done",
        expected=_routes(True),
    ),
]

# What the agent should stay out of. These are the failures the suite exists to catch:
# every one of them is about the work or about the agent, and none is addressed to it.
CHATTER_CASES = [
    BaseEvalCase(
        name="bare_acknowledgement",
        prompt="thanks!",
        expected=_routes(False),
    ),
    BaseEvalCase(
        name="human_to_human",
        prompt="@bob do you remember why we wrapped the handler in that debounce?",
        expected=_routes(False),
    ),
    BaseEvalCase(
        name="off_topic",
        prompt="lunch in 5?",
        expected=_routes(False),
    ),
    BaseEvalCase(
        name="emoji_only",
        prompt=":tada: :rocket:",
        expected=_routes(False),
    ),
    BaseEvalCase(
        name="approval_without_content",
        prompt="nice, that was quick",
        expected=_routes(False),
    ),
    # Opinions about the work, said to the room. Task-relevant, and the single biggest
    # source of spurious wake-ups: relevant is not the same as addressed.
    BaseEvalCase(
        name="opinion_about_the_product",
        prompt="this whole thing would probably benefit from a proper Settings section",
        expected=_routes(False),
    ),
    BaseEvalCase(
        name="design_opinion",
        prompt="def needs a stronger label imo",
        expected=_routes(False),
    ),
    BaseEvalCase(
        name="shared_frustration",
        prompt="I've seen this get set back and forth so many times",
        expected=_routes(False),
    ),
    # Talk about the agent. Being the topic is not being the audience.
    BaseEvalCase(
        name="question_about_the_bot",
        prompt="why did the bot just react to me? is it supposed to do that?",
        expected=_routes(False),
    ),
    BaseEvalCase(
        name="commentary_on_the_bot",
        prompt="it keeps jumping in without doing any actual work lol",
        expected=_routes(False),
    ),
    # Context with no instruction attached — a link dropped for the humans to look at.
    BaseEvalCase(
        name="link_without_an_ask",
        prompt="same thing happened here I think https://posthog.slack.com/archives/C123/p456",
        expected=_routes(False),
    ),
    # Two humans settling something between themselves.
    BaseEvalCase(
        name="agreement_between_humans",
        prompt="yeah go for it, that was my read too",
        expected=_routes(False),
    ),
]


async def eval_followup_classifier(ctx: EvalContext) -> None:
    require_llm_gateway()

    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        # Recorded on every case so an experiment says which model produced its scores —
        # otherwise two runs of the same suite are indistinguishable in the history, which
        # is exactly what you go to the history to compare.
        classifier_model = classifiers.ROUTING_CLASSIFIER_MODEL
        try:
            # Sync and blocking on the gateway — off the event loop so cases still run
            # concurrently under the harness's limiter.
            agent_directed = await asyncio.to_thread(
                classifiers.classify_message_is_agent_directed, case.prompt, TASK_TITLE, THREAD
            )
        except Exception as error:
            return {
                "classifier_model": classifier_model,
                "agent_directed": None,
                "error": f"{type(error).__name__}: {error}",
            }
        return {
            "classifier_model": classifier_model,
            "agent_directed": agent_directed,
            "last_message": f"{classifier_model}: agent_directed={agent_directed}",
        }

    await OneShotPublicEval(
        experiment_name="slack-app-followup-classifier",
        cases=[*DIRECTED_CASES, *CHATTER_CASES],
        scorers=[FollowupRoutingMatch(), NoUnaskedWake()],
        task=task,
        ctx=ctx,
    )
