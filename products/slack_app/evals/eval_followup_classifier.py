"""In a thread the agent is working in, which untagged replies are instructions to it?

Once the Slack App picks up a task, people stop tagging it. They talk about the work,
about the product, about the agent, and occasionally to it. Every reply hits
`classify_message_is_agent_directed`, which decides whether the agent wakes up.

The errors are not symmetric, which is why `no_unasked_wake` is the number to watch rather
than accuracy — see `classify_message_is_agent_directed` for why.

The chatter cases are the point of the suite: they are the shapes the classifier woke on
in real threads. None of the cases reuses the prompt's own examples, which would measure
whether the model can copy a list it was just handed.

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
from products.slack_app.backend.services.slack_messages import SlackThreadMessage
from products.slack_app.evals.scorers import FOLLOWUP_KEY, FollowupRoutingMatch, NoUnaskedWake

SUITE_KIND = SuiteKind.ONE_SHOT

TASK_TITLE = "Fix the checkout button not firing autocapture events"

# The thread most cases continue: a human asked, the agent acknowledged.
THREAD = [
    SlackThreadMessage(
        user="alice", text="@PostHog autocapture isn't picking up clicks on our checkout button", ts="1.0"
    ),
    SlackThreadMessage(user="posthog", text="Looking into it — checking how the button is rendered.", ts="2.0"),
]

# Threads where a second coding agent works alongside us. A reply that tags it never
# reaches the classifier (``_bot_addressed_by_reply`` drops it), so these cases are the
# replies that name nobody, and only what each agent said says who they answer.
THREAD_OTHER_AGENT_ASKED = [
    *THREAD,
    SlackThreadMessage(
        user="cursor",
        text="I have the checkout page open for the layout refactor. Shall I move the click handler out of the wrapper while I am in there?",
        ts="3.0",
    ),
]
THREAD_POSTHOG_ASKED = [
    *THREAD,
    SlackThreadMessage(user="cursor", text="Heads up, that whole file moves in my refactor branch.", ts="3.0"),
    SlackThreadMessage(
        user="posthog",
        text="Do you want the handler fixed where it is now, or should I wait for that refactor to land?",
        ts="4.0",
    ),
]

THREADS = {
    "default": THREAD,
    "other_agent_asked": THREAD_OTHER_AGENT_ASKED,
    "posthog_asked": THREAD_POSTHOG_ASKED,
}


def _routes(agent_directed: bool) -> dict:
    return {FOLLOWUP_KEY: {"agent_directed": agent_directed}}


def _in_thread(name: str) -> dict:
    return {"thread": name}


# Instructions. Only the first addresses the agent by name; the rest are what people
# actually type once they have stopped tagging.
DIRECTED_CASES = [
    BaseEvalCase(
        name="direct_instruction",
        prompt="@PostHog one more thing while you're in there — make sure it doesn't double-fire",
        expected=_routes(True),
    ),
    BaseEvalCase(
        name="scope_correction",
        prompt="leave the analytics wrapper alone, only touch the click handler",
        expected=_routes(True),
    ),
    BaseEvalCase(
        name="question_about_the_work",
        prompt="what did you end up changing in the tracking snippet?",
        expected=_routes(True),
    ),
    BaseEvalCase(
        name="order_to_retry",
        prompt="start over from the cart page instead, that's where it actually breaks",
        expected=_routes(True),
    ),
    BaseEvalCase(
        name="correction_of_the_agent",
        prompt="that's the wrong file — it's the one under components/, not lib/",
        expected=_routes(True),
    ),
    # A second agent in the thread must not make us deaf to an answer we asked for.
    BaseEvalCase(
        name="answer_to_our_own_question",
        prompt="fix it where it is now, we can rebase later",
        expected=_routes(True),
        metadata=_in_thread("posthog_asked"),
    ),
    BaseEvalCase(
        name="follow_up_ask",
        prompt="can you add a test for the logged-out case as well",
        expected=_routes(True),
    ),
]

# What the agent should stay out of. Every one is about the work or about the agent, and
# none is addressed to it.
CHATTER_CASES = [
    BaseEvalCase(name="bare_acknowledgement", prompt="cheers", expected=_routes(False)),
    BaseEvalCase(
        name="human_to_human",
        prompt="@bob any idea when we added that debounce?",
        expected=_routes(False),
    ),
    BaseEvalCase(name="off_topic", prompt="standup moved to 3 btw", expected=_routes(False)),
    BaseEvalCase(name="approval_without_content", prompt="oh nice, that was fast", expected=_routes(False)),
    # Opinions said to the room. Task-relevant, and the biggest source of spurious
    # wake-ups: relevant is not the same as addressed.
    BaseEvalCase(
        name="opinion_about_the_product",
        prompt="honestly the whole checkout flow could use a rethink at some point",
        expected=_routes(False),
    ),
    BaseEvalCase(
        name="design_opinion",
        prompt="the copy on that button has bugged me for ages",
        expected=_routes(False),
    ),
    BaseEvalCase(
        name="shared_frustration",
        prompt="this exact thing bit us last quarter too",
        expected=_routes(False),
    ),
    # Talk about the agent. Being the topic is not being the audience.
    BaseEvalCase(
        name="question_about_the_bot",
        prompt="wait, why did it just eyes-react to my message?",
        expected=_routes(False),
    ),
    BaseEvalCase(
        name="commentary_on_the_bot",
        prompt="lol it's lurking in every thread now",
        expected=_routes(False),
    ),
    BaseEvalCase(
        name="link_without_an_ask",
        prompt="related: https://posthog.slack.com/archives/C123/p456",
        expected=_routes(False),
    ),
    BaseEvalCase(
        name="agreement_between_humans",
        prompt="yep, same conclusion I came to",
        expected=_routes(False),
    ),
    # Orders aimed at a person. The @mention that would settle who is being asked is the
    # first thing people drop once a thread is moving, which leaves the imperative — the
    # shape the agent reads as its own instruction.
    BaseEvalCase(
        name="instruction_to_a_named_human",
        prompt="sam go ahead and put yourself down as reviewer on that PR too",
        expected=_routes(False),
    ),
    BaseEvalCase(
        name="request_only_a_person_can_do",
        prompt="if you could join the call with their eng team tomorrow that would be great too",
        expected=_routes(False),
    ),
    # Someone picking the work up themselves. The agent read this as its own go-ahead and
    # answered to say it was standing aside, which is itself the interruption.
    BaseEvalCase(
        name="colleague_claims_the_work",
        prompt="ah I see what's going on, let me fix that",
        expected=_routes(False),
    ),
    # A proposal put to colleagues mid-debate. Argued and task-relevant, so it reads far
    # more like an instruction than the offhand opinions above do.
    BaseEvalCase(
        name="proposal_in_a_debate",
        prompt="hmm, I'd be more inclined to drop the wrapper entirely and handle it at the call site",
        expected=_routes(False),
    ),
    # Every word of it is about our task; the only thing that says it is not for us is
    # which agent asked.
    BaseEvalCase(
        name="answer_to_another_agents_question",
        prompt="that's fine, pull it out of the wrapper while you're in there",
        expected=_routes(False),
        metadata=_in_thread("other_agent_asked"),
    ),
    # A thread kept as a running list. The item carries an implicit work item, which is a
    # sharper lure than a bare link.
    BaseEvalCase(
        name="bookkeeping_entry",
        prompt="https://posthog.slack.com/archives/C123/p456 checkout-button@example.com",
        expected=_routes(False),
    ),
]


async def eval_followup_classifier(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        # Recorded per case so an experiment says which model produced its scores.
        classifier_model = classifiers.AGENT_DIRECTED_CLASSIFIER_MODEL
        try:
            # Sync and blocking on the gateway — off the event loop so cases still run
            # concurrently under the harness's limiter.
            agent_directed = await asyncio.to_thread(
                classifiers.classify_message_is_agent_directed,
                case.prompt,
                TASK_TITLE,
                THREADS[case.metadata.get("thread", "default")],
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
