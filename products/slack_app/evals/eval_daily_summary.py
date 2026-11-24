"""Does the daily summary tell a person what moved in their channels, and leave out the chatter?

The daily work focus opens with a summary of the threads that moved in the channels a person
shares with the bot. Two model calls shape it, and each suite here grades one:

- `eval_daily_summary_rank`: the sweep asks Jev, for each thread root, whether a teammate who
  missed the day would want to know. `score_roots` scores every root of the invented
  `slack_workspace` that has a fair answer. The real sweep scores up to 32 roots in one call;
  here each root goes alone, so a score never depends on its neighbours.
- `eval_daily_summary_write`: `pick_threads` picks a day's threads from the index the way a run
  does, with each root scored from its label, and `write_work_focus` writes the summary. The
  person's own threads come first even when they are only chat, so the writer has to leave
  those out itself.

`summary_covers` is the number to watch for the writer: a summary that misses the day's
incident fails the person more than one that keeps a borderline thread. `summary_intro_fits`
checks that the first line leads into the items instead of calling them the person's work, and
`summary_not_clipped` that no line ran over its limit and lost its end.

To run:
    hogli evals eval_daily_summary
    hogli evals eval_daily_summary_write --eval quiet_day
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotEval
from products.slack_app.backend.logic.onboarding import daily_summary, work_focus
from products.slack_app.evals import slack_workspace
from products.slack_app.evals.offline_config import offline_suite
from products.slack_app.evals.scorers import (
    DAILY_SUMMARY_RANK_KEY,
    DAILY_SUMMARY_WRITE_KEY,
    DailySummaryRankMatch,
    SummaryCovers,
    SummaryFaithful,
    SummaryIntroFits,
    SummaryNotClipped,
    SummaryOmitsChatter,
    SummaryVoice,
)

SUITE_KIND = SuiteKind.ONE_SHOT

PERSON = work_focus.DigestPerson(slack_user_id=slack_workspace.PERSON.user_id, name=slack_workspace.PERSON.name)
PEOPLE_NAMES = [member.name for member in slack_workspace.MEMBERS if not member.is_bot]
# The run reads back to the previous workday's run, which here is the start of the day.
SINCE = slack_workspace.DAY_START - timedelta(minutes=1)
# Stand-ins for Jev's scores, so the writer suite grades the writer alone.
LABEL_SCORES = {True: 0.9, None: 0.6, False: 0.1}

RANK_CASES = [
    BaseEvalCase(
        name=thread.key,
        prompt=thread.root.text,
        expected={DAILY_SUMMARY_RANK_KEY: {"newsworthy": thread.newsworthy}},
    )
    for thread in slack_workspace.THREADS
    if thread.newsworthy is not None
]


def _day(name: str, keys: list[str], *, must_cover=(), must_omit=(), you_for=()) -> BaseEvalCase:
    return BaseEvalCase(
        name=name,
        prompt=f"The daily summary for {slack_workspace.PERSON.name} from: {', '.join(keys)}",
        expected={
            DAILY_SUMMARY_WRITE_KEY: {
                "must_cover": list(must_cover),
                "must_omit": list(must_omit),
                "you_for": list(you_for),
                "names": PEOPLE_NAMES,
            }
        },
        metadata={"threads": keys},
    )


WRITE_CASES = [
    # The person's own decision, a lunch thread they joined, and three threads of news.
    _day(
        "own_decision_and_news",
        [
            "decision_trial_length",
            "chat_lunch",
            "incident_upload_outage",
            "launch_shared_folders",
            "blocker_release_migration",
        ],
        must_cover=["decision_trial_length", "incident_upload_outage", "blocker_release_migration"],
        must_omit=["chat_lunch"],
        you_for=["decision_trial_length"],
    ),
    # Nothing happened: the only thread that reaches the writer is a lunch the person joined.
    _day(
        "quiet_day",
        ["chat_lunch", "answered_2fa_reset", "status_heads_down", "chat_good_morning"],
        must_omit=["chat_lunch"],
    ),
    # Requests to the person, work they handed to an agent, a finished fix, and an incident.
    _day(
        "asks_and_handoffs",
        [
            "ask_onboarding_copy",
            "open_storage_usage_blocker",
            "handed_off_thumbnail_bug",
            "done_utm_params",
            "incident_upload_outage",
        ],
        must_cover=["ask_onboarding_copy", "open_storage_usage_blocker", "incident_upload_outage"],
    ),
]


def _rank(team_id: int, case: BaseEvalCase) -> float:
    thread = slack_workspace.BY_KEY[case.name]
    scored = daily_summary.score_roots(team_id, [slack_workspace.root_ref(thread)], [slack_workspace.root_text(thread)])
    return scored[0].score


def _write(team_id: int, case: BaseEvalCase) -> dict:
    threads = [slack_workspace.BY_KEY[key] for key in case.metadata["threads"]]
    by_root = {(thread.channel_id, slack_workspace.root_ref(thread).ts): thread for thread in threads}
    picked = daily_summary.pick_threads(
        [slack_workspace.root_ref(thread, LABEL_SCORES[thread.newsworthy]) for thread in threads],
        PERSON.slack_user_id,
        set(slack_workspace.CHANNELS),
        since=SINCE,
        bot_user_id=slack_workspace.POSTHOG.user_id,
    )
    picked_threads = [by_root[(root.channel_id, root.ts)] for root in picked]
    focus = work_focus.write_work_focus(
        team_id,
        [],
        flow="slack_app_daily_focus",
        threads=[slack_workspace.summary_thread(thread) for thread in picked_threads],
        person=PERSON,
    )
    key_of = {slack_workspace.permalink(thread): thread.key for thread in picked_threads}
    items = [{"text": item.text, "source": key_of.get(item.permalink or "")} for item in focus.summary]
    return {
        "person": f"<@{PERSON.slack_user_id}>",
        "picked": [thread.key for thread in picked_threads],
        "threads": [{"key": thread.key, "text": slack_workspace.text_of(thread)} for thread in picked_threads],
        "intro": focus.intro,
        "items": items,
        "last_message": "\n".join([focus.intro, *(f"- [{item['source']}] {item['text']}" for item in items)]),
    }


async def eval_daily_summary_rank(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        model = daily_summary.RANK_MODEL
        if task_ctx.demo_data is None:
            return {"decision_model": model, "newsworthy": None, "error": "No demo data team to bill the call to"}
        try:
            # Sync and blocking on the gateway, so off the event loop.
            probability = await asyncio.to_thread(_rank, task_ctx.demo_data.master_team_id, case)
        except Exception as error:
            return {"decision_model": model, "newsworthy": None, "error": f"{type(error).__name__}: {error}"}
        newsworthy = probability >= daily_summary.RANK_MIN_PROBABILITY
        return {
            "decision_model": model,
            "newsworthy": newsworthy,
            "probability": probability,
            "last_message": f"{model}: newsworthy={newsworthy} ({probability:.2f})",
        }

    await OneShotEval(
        experiment_name="slack-app-daily-summary-rank",
        offline_suite=offline_suite(
            "slack_app/eval_daily_summary::eval_daily_summary_rank",
            metrics=[DAILY_SUMMARY_RANK_KEY],
            suite_kind=SUITE_KIND,
        ),
        cases=RANK_CASES,
        scorers=[DailySummaryRankMatch()],
        task=task,
        ctx=ctx,
    )


async def eval_daily_summary_write(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        model = work_focus.WRITE_MODEL
        if task_ctx.demo_data is None:
            return {"write_model": model, "items": [], "error": "No demo data team to bill the call to"}
        try:
            output = await asyncio.to_thread(_write, task_ctx.demo_data.master_team_id, case)
        except Exception as error:
            return {"write_model": model, "items": [], "error": f"{type(error).__name__}: {error}"}
        return {"write_model": model, **output}

    await OneShotEval(
        experiment_name="slack-app-daily-summary-write",
        offline_suite=offline_suite(
            "slack_app/eval_daily_summary::eval_daily_summary_write",
            metrics=[
                "summary_covers",
                "summary_omits_chatter",
                "summary_voice",
                "summary_faithful",
                "summary_intro_fits",
                "summary_not_clipped",
            ],
            suite_kind=SUITE_KIND,
        ),
        cases=WRITE_CASES,
        scorers=[
            SummaryCovers(),
            SummaryOmitsChatter(),
            SummaryVoice(),
            SummaryFaithful(),
            SummaryIntroFits(),
            SummaryNotClipped(),
        ],
        task=task,
        ctx=ctx,
    )
