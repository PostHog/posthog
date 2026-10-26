"""Which agent answers get one-click reply buttons, and are the buttons ones a person would press?

Each case prompt is the agent's answer, not a user request. Watch `no_unasked_buttons` first,
for the reason `suggest_replies` gives, then `reply_offer`, then `suggested_replies_fit`.

To run:
    hogli evals eval_reply_suggestions
    hogli evals eval_reply_suggestions --eval rhetorical_question
"""

from __future__ import annotations

import asyncio

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPublicEval
from products.slack_app.backend.logic import reply_suggestions
from products.slack_app.evals.offline_config import offline_suite
from products.slack_app.evals.scorers import REPLY_OFFER_KEY, NoUnaskedButtons, ReplyOfferMatch, SuggestedRepliesFit

SUITE_KIND = SuiteKind.ONE_SHOT


# The person's last message, when a case needs it to show who decides or what they want.
PERSON_MESSAGE_KEY = "person_message"


def _offer(offer: bool) -> dict:
    return {REPLY_OFFER_KEY: {"offer": offer}}


# Longer than the clip window, with the question only in the tail.
_MIGRATION_STEP = (
    "Step {n}: the backfill reads one day of `signed_up` events, writes them to the new table, "
    "and checks that the row counts match before it moves on. A mismatch stops the run and "
    "logs the day, so a rerun starts from that day and not from the beginning.\n\n"
)
LONG_ANSWER = (
    "I wrote the plan for the backfill. It runs one day at a time:\n\n"
    + "".join(_MIGRATION_STEP.format(n=n) for n in range(1, 31))
    + "The whole run takes about two hours. Should I start it now, or wait until tonight?"
)

WAITING_CASES = [
    BaseEvalCase(
        name="permission_to_open_pr",
        prompt=(
            "I found the cause. The retry loop resets its counter on every attempt, so it never stops "
            "after a failure. The fix is two lines in `relay.py`. Should I open a pull request with it?"
        ),
        expected=_offer(True),
        metadata={PERSON_MESSAGE_KEY: "Why does the relay keep retrying after the export fails?"},
    ),
    BaseEvalCase(
        name="choice_between_options",
        prompt=(
            "Here are two layouts for the pricing table:\n\n"
            "1. **Plans as columns**: easy to compare, but tight on small screens.\n"
            "2. **Plans as cards**: roomier, but the features do not line up.\n\n"
            "Which one do you want?"
        ),
        expected=_offer(True),
    ),
    BaseEvalCase(
        name="offer_of_a_next_step",
        prompt=(
            "Signups went up 12% last week compared to the week before. Most of the rise came on Tuesday. "
            "I can break this down by acquisition source if that helps."
        ),
        expected=_offer(True),
    ),
    BaseEvalCase(
        name="plan_to_confirm",
        prompt=(
            "Here is my plan:\n\n"
            "1. Add a `retries` column to the export table.\n"
            "2. Retry a failed export up to three times.\n"
            "3. Alert the owner after the third failure.\n\n"
            "Does this plan look right before I start?"
        ),
        expected=_offer(True),
    ),
    BaseEvalCase(
        name="question_after_a_long_answer",
        prompt=LONG_ANSWER,
        expected=_offer(True),
    ),
    # One option is complete, the other needs a name only the person knows, so its buttons
    # must not guess the name or say the same thing twice.
    BaseEvalCase(
        name="open_question_beside_a_choice",
        prompt=(
            "The `orders` table has no rows, so I can't count last month's revenue. "
            "Is there another table I should use, or should I help you connect your Stripe source first?"
        ),
        expected=_offer(True),
    ),
    # A reader often wants only the check. One button that also opens the pull request takes that choice away.
    BaseEvalCase(
        name="investigation_before_a_change",
        prompt=(
            "Export jobs got slower this week. The median run went from 40s to 3 minutes, and only the jobs "
            "that read the `invoices` table slowed down. A missing index is the most likely cause, but I did "
            "not check the query plan. Next I can run EXPLAIN on the slow query, and if the index is missing, "
            "add it in a migration and open a pull request. Do you want me to do that?"
        ),
        expected=_offer(True),
    ),
    # Buttons for every mix of the two answers would differ by one word each and leave a mix out.
    BaseEvalCase(
        name="two_separate_questions",
        prompt=(
            "The weekly digest is ready. Two things to decide:\n\n"
            "1. **Channel:** email reaches everyone, and Slack reaches only the team that joined the "
            "`#digest` channel. I recommend Slack, because the email list has many old addresses.\n"
            "2. **Day:** Monday or Friday. I suggest Monday, so the numbers are fresh for the week.\n\n"
            "Which channel and which day do you want?"
        ),
        expected=_offer(True),
    ),
    BaseEvalCase(
        name="permission_in_german",
        prompt=(
            "Ich habe den Fehler gefunden: Der Export bricht ab, wenn eine Datei leer ist. "
            "Soll ich den Fix als Pull Request öffnen?"
        ),
        expected=_offer(True),
    ),
]

# Each one is a lure: a question mark, a polite invitation, or a request only the person can fill.
BARE_CASES = [
    BaseEvalCase(
        name="plain_result",
        prompt="There were 4,212 pageviews yesterday, about the same as the day before.",
        expected=_offer(False),
    ),
    BaseEvalCase(
        name="explanation",
        prompt=(
            "The `beta-dashboards` flag turns on the new dashboard layout. It is on for 20% of users "
            "in the Hedgebox organization, and the rollout has not changed since last month."
        ),
        expected=_offer(False),
    ),
    BaseEvalCase(
        name="work_reported_done",
        prompt="I opened the pull request: https://github.com/example/app/pull/42. CI is running now.",
        expected=_offer(False),
    ),
    BaseEvalCase(
        name="rhetorical_question",
        prompt=(
            "Why did the nightly export fail? The bucket policy blocked the write. "
            "I updated the policy and ran the export again, and it finished."
        ),
        expected=_offer(False),
    ),
    BaseEvalCase(
        name="polite_sign_off",
        prompt="Done. The alert now fires at 5% instead of 10%. Let me know if you need anything else.",
        expected=_offer(False),
    ),
    # The reader cannot make this decision, so a button would commit to a choice for another team.
    BaseEvalCase(
        name="decision_waits_for_another_team",
        prompt=(
            "The billing team is choosing between monthly and yearly usage caps. If they pick monthly caps, "
            "I can open the pull request for the new limit. If they pick yearly caps, the current branch is "
            "ready to merge as it is."
        ),
        expected=_offer(False),
        metadata={PERSON_MESSAGE_KEY: "What is left before we can ship the usage caps?"},
    ),
    # Only the person can answer this, and a button would have to guess the repository.
    BaseEvalCase(
        name="asks_for_a_value_only_the_person_knows",
        prompt="I couldn't find the export settings in any connected repository. Which repository are they in?",
        expected=_offer(False),
    ),
]


async def eval_reply_suggestions(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        model = reply_suggestions.SUGGESTIONS_MODEL
        person_message = case.metadata.get(PERSON_MESSAGE_KEY)
        try:
            # Sync and blocking on the gateway, so off the event loop to keep cases concurrent.
            suggestions = await asyncio.to_thread(
                reply_suggestions.request_reply_suggestions,
                case.prompt,
                reply_suggestions.ReplySuggestionAttribution(),
                person_message,
            )
        except Exception as error:
            return {"model": model, "suggestions": None, "error": f"{type(error).__name__}: {error}"}
        offered = [{"label": s.label, "reply": s.reply} for s in suggestions]
        return {
            "model": model,
            "suggestions": offered,
            "person_message": person_message,
            "last_message": f"{model}: {offered}",
        }

    await OneShotPublicEval(
        experiment_name="slack-app-reply-suggestions",
        offline_suite=offline_suite(
            "slack_app/eval_reply_suggestions::eval_reply_suggestions",
            metrics=["reply_offer", "no_unasked_buttons", "suggested_replies_fit"],
            suite_kind=SUITE_KIND,
        ),
        cases=[*WAITING_CASES, *BARE_CASES],
        scorers=[ReplyOfferMatch(), NoUnaskedButtons(), SuggestedRepliesFit()],
        task=task,
        ctx=ctx,
    )
