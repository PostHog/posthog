"""Does the work focus leave alone the work people already handed to another AI agent?

The daily work focus offers to do work from the Slack messages that mention a person. Code drops
a message or a thread that tags any Slack app, so these cases are the handoffs no tag shows:
"Claude is on it", "I gave it to Devin". Only Jev can read those, in two places:
`rank_messages` decides whether a message holds work for PostHog, and `drop_finished` decides
whether its thread still asks for that work.

An offer for handed-off work makes PostHog compete with the agent the person already chose, so
`no_handed_off_offer` is the number to watch. `work_focus_keep` also holds the real asks, so a
prompt that drops everything cannot post a perfect score. The traps name an agent without
handing it the work. The thread cases are the threads of the invented `slack_workspace` that
asked the person for work, the same conversations the daily summary suites read.

To run:
    hogli evals eval_work_focus_handoff
    hogli evals eval_work_focus_handoff --eval asked_claude_without_a_tag
"""

from __future__ import annotations

import asyncio

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotEval
from products.slack_app.backend.logic.onboarding import work_focus
from products.slack_app.backend.logic.onboarding.work_focus import DigestPerson, FoundMessage
from products.slack_app.evals import slack_workspace
from products.slack_app.evals.offline_config import offline_suite
from products.slack_app.evals.scorers import WORK_FOCUS_KEEP_KEY, NoHandedOffOffer, WorkFocusKeepMatch

SUITE_KIND = SuiteKind.ONE_SHOT

PERSON = DigestPerson(slack_user_id=slack_workspace.PERSON.user_id, name=slack_workspace.PERSON.name)


def _keep(keep: bool, *, handed_off: bool = False) -> dict:
    return {WORK_FOCUS_KEEP_KEY: {"keep": keep, "handed_off": handed_off}}


# `rank_messages`: one message that mentions the person, with no thread.
ASKS = [
    BaseEvalCase(
        name="data_question",
        prompt="<@U0DANA> signups from the pricing page dropped since Tuesday, can you dig into why?",
        expected=_keep(True),
    ),
    BaseEvalCase(
        name="bug_report",
        prompt="<@U0DANA> the export endpoint returns 500 for large projects, can you look before the release?",
        expected=_keep(True),
    ),
    # An agent is the subject, not the assignee: its answer was wrong and the work is open.
    BaseEvalCase(
        name="agent_answer_was_wrong",
        prompt="<@U0DANA> Claude's numbers on weekly retention looked off, can you check the real data?",
        expected=_keep(True),
    ),
    BaseEvalCase(
        name="agent_as_a_tool_choice",
        prompt="<@U0DANA> no idea if Cursor can help here, but the dashboard load time doubled, can you find out why?",
        expected=_keep(True),
    ),
]

HANDOFFS = [
    BaseEvalCase(
        name="asked_claude_without_a_tag",
        prompt="<@U0DANA> I already asked Claude to fix the flaky login test, it's on it",
        expected=_keep(False, handed_off=True),
    ),
    BaseEvalCase(
        name="cursor_owns_the_refactor",
        prompt="<@U0DANA> Cursor is refactoring the billing page right now, so leave that one",
        expected=_keep(False, handed_off=True),
    ),
    BaseEvalCase(
        name="gave_it_to_devin",
        prompt="<@U0DANA> I gave the CSV export bug to Devin this morning, the PR should land soon",
        expected=_keep(False, handed_off=True),
    ),
    BaseEvalCase(
        name="copilot_opened_a_draft",
        prompt="<@U0DANA> the Copilot agent opened a draft PR for the dark mode toggle",
        expected=_keep(False, handed_off=True),
    ),
    BaseEvalCase(
        name="codex_still_running",
        prompt="<@U0DANA> the Codex run is still on the search timeout, I'll ping you when it's done",
        expected=_keep(False, handed_off=True),
    ),
]

# `drop_finished`: every workspace thread whose root asked the person for work. Only the replies
# say whether that work is still open, went to an agent, or is done.
THREADS = [
    BaseEvalCase(
        name=f"thread_{thread.key}",
        prompt=thread.root.text,
        expected=_keep(thread.work == "open", handed_off=thread.work == "handed_off"),
        metadata={"thread": slack_workspace.text_of(thread)},
    )
    for thread in slack_workspace.THREADS
    if thread.work is not None
]


def _found(case: BaseEvalCase) -> FoundMessage:
    return FoundMessage(
        content=case.prompt,
        channel_id="C0GROWTH",
        thread_ts="1700000000.000100",
        channel_name="product",
        permalink=None,
        author_id=slack_workspace.ANA.user_id,
        thread=case.metadata.get("thread"),
    )


def _kept(team_id: int, case: BaseEvalCase) -> bool:
    message = _found(case)
    if message.thread is None:
        kept = work_focus.rank_messages(team_id, [message], flow="slack_app_daily_focus", person=PERSON)
    else:
        kept = work_focus.drop_finished(team_id, [message], flow="slack_app_daily_focus", person=PERSON)
    return bool(kept)


async def eval_work_focus_handoff(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        model = work_focus.RANK_MODEL
        if task_ctx.demo_data is None:
            return {"decision_model": model, "kept": None, "error": "No demo data team to bill the call to"}
        try:
            # Sync and blocking on the gateway, so off the event loop.
            kept = await asyncio.to_thread(_kept, task_ctx.demo_data.master_team_id, case)
        except Exception as error:
            return {"decision_model": model, "kept": None, "error": f"{type(error).__name__}: {error}"}
        return {"decision_model": model, "kept": kept, "last_message": f"{model}: kept={kept}"}

    await OneShotEval(
        experiment_name="slack-app-work-focus-handoff",
        offline_suite=offline_suite(
            "slack_app/eval_work_focus_handoff::eval_work_focus_handoff",
            metrics=[WORK_FOCUS_KEEP_KEY, "no_handed_off_offer"],
            suite_kind=SUITE_KIND,
        ),
        cases=[*ASKS, *HANDOFFS, *THREADS],
        scorers=[WorkFocusKeepMatch(), NoHandedOffOffer()],
        task=task,
        ctx=ctx,
    )
