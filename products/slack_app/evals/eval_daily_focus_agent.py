"""Does the daily focus agent tell a person only what is new to them, and offer only work nobody took?

The agent version of the daily work focus reads Slack through the person's Slack MCP and answers once
with JSON, which `to_work_focus` checks before the DM renders. This suite sends the production
prompt and model one day of the invented `slack_workspace`, with the threads in the prompt in place
of the Slack tools, and grades what `to_work_focus` keeps, so a case fails only when the person
would see the mistake.

- `agent_covers` and `agent_sections`: the DM shows what asks or mentions the person under
  "For you", and the team's news under "In your channels".
- `agent_omits_known`: the person's own threads, threads they answered last, resolved work, work
  an agent took, and chat stay out.
- `agent_offer_recall` and `no_reacted_offer`: the DM offers the request nobody reacted to, and
  never work someone replied to, took or handed to an agent.

The sandbox, the Slack MCP and the tool calls are not graded here, only what the prompt makes of
the threads.

To run:
    hogli evals eval_daily_focus_agent
    hogli evals eval_daily_focus_agent --eval quiet_day
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from zoneinfo import ZoneInfo

from posthog.llm.gateway_client import build_anthropic_client, team_distinct_id
from posthog.llm.semantic_enrichment import extract_json_object

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotEval
from products.slack_app.backend.logic.onboarding import daily_focus_agent
from products.slack_app.evals import slack_workspace
from products.slack_app.evals.offline_config import offline_suite
from products.slack_app.evals.scorers import (
    DAILY_FOCUS_AGENT_KEY,
    DAILY_SUMMARY_WRITE_KEY,
    AgentCovers,
    AgentOfferRecall,
    AgentOmitsKnown,
    AgentSections,
    NoReactedOffer,
    SummaryFaithful,
    SummaryVoice,
)

SUITE_KIND = SuiteKind.ONE_SHOT

PERSON = slack_workspace.PERSON
PEOPLE_NAMES = [member.name for member in slack_workspace.MEMBERS if not member.is_bot]
ZONE = ZoneInfo("UTC")
SINCE = slack_workspace.DAY_START - timedelta(minutes=1)
MAX_TOKENS = 8192


def _day(
    name: str,
    keys: list[str],
    *,
    must_cover: dict[str, str] | None = None,
    must_omit=(),
    offers=(),
    no_offer=(),
) -> BaseEvalCase:
    return BaseEvalCase(
        name=name,
        prompt=f"The daily focus agent for {PERSON.name} from: {', '.join(keys)}",
        expected={
            DAILY_FOCUS_AGENT_KEY: {
                "must_cover": must_cover or {},
                "must_omit": list(must_omit),
                "offers": list(offers),
                "no_offer": list(no_offer),
            },
            # Read by `summary_voice` alone: the agent names people by token, never by name.
            DAILY_SUMMARY_WRITE_KEY: {"names": PEOPLE_NAMES},
        },
        metadata={"threads": keys},
    )


CASES = [
    # An ask nobody answered and a launch, next to the person's own decision, a question they answered, a finished
    # fix and chat.
    _day(
        "new_to_you_and_news",
        [
            "incident_upload_outage",
            "decision_trial_length",
            "launch_shared_folders",
            "blocker_release_migration",
            "unanswered_usage_ask",
            "answered_by_person",
            "done_utm_params",
            "chat_lunch",
            "chat_good_morning",
        ],
        must_cover={"unanswered_usage_ask": "for_you", "launch_shared_folders": "news"},
        must_omit=["decision_trial_length", "answered_by_person", "done_utm_params", "chat_lunch", "chat_good_morning"],
        offers=["unanswered_usage_ask"],
        no_offer=["decision_trial_length", "answered_by_person", "done_utm_params"],
    ),
    # Nothing new: chat, a status note and questions that were already answered.
    _day(
        "quiet_day",
        ["chat_lunch", "chat_good_morning", "status_heads_down", "answered_2fa_reset", "answered_by_person"],
        must_omit=["chat_lunch", "chat_good_morning", "status_heads_down", "answered_2fa_reset", "answered_by_person"],
        no_offer=["answered_2fa_reset", "answered_by_person"],
    ),
    # Work handed to agents, taken by a teammate, or discussed already, next to the one request nobody touched.
    _day(
        "handoffs_and_reactions",
        [
            "handed_off_thumbnail_bug",
            "handed_off_rename_event",
            "tagged_claude_directly",
            "taken_by_teammate",
            "open_trial_conversion_drop",
            "open_storage_usage_blocker",
            "unanswered_usage_ask",
            "asked_posthog_app",
        ],
        must_cover={"unanswered_usage_ask": "for_you", "open_storage_usage_blocker": "for_you"},
        must_omit=[
            "handed_off_thumbnail_bug",
            "handed_off_rename_event",
            "tagged_claude_directly",
            "asked_posthog_app",
        ],
        offers=["unanswered_usage_ask"],
        no_offer=[
            "handed_off_thumbnail_bug",
            "handed_off_rename_event",
            "tagged_claude_directly",
            "taken_by_teammate",
            "open_trial_conversion_drop",
            "open_storage_usage_blocker",
            "asked_posthog_app",
        ],
    ),
]


def _thread_block(thread: slack_workspace.Thread) -> str:
    """The thread as the Slack MCP shows it: app posts included, because an agent's reply is how the person sees
    that the work was taken."""
    lines = [
        f"Thread in #{slack_workspace.CHANNELS[thread.channel_id]} (channel {thread.channel_id}): "
        f"{slack_workspace.permalink(thread)}"
    ]
    for message in thread.messages:
        at = (slack_workspace.DAY_START + timedelta(minutes=message.minutes)).astimezone(ZONE)
        lines.append(f"[{at:%H:%M}] <@{message.user}>: {message.text}")
    return "\n".join(lines)


def _ask(team_id: int, case: BaseEvalCase) -> dict:
    threads = [slack_workspace.BY_KEY[key] for key in case.metadata["threads"]]
    prompt = daily_focus_agent.render_prompt(
        PERSON.user_id,
        since=SINCE,
        zone=ZONE,
        threads="\n\n".join(_thread_block(thread) for thread in threads),
    )
    client = build_anthropic_client(ai_product="slack_app", team_id=team_id, distinct_id=team_distinct_id(team_id))
    response = client.messages.create(
        model=daily_focus_agent.AGENT_MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    reply = "".join(block.text for block in response.content if block.type == "text")
    parsed = extract_json_object(reply)
    if parsed is None:
        raise ValueError(f"The reply is not a JSON object: {reply[:200]}")
    answer = daily_focus_agent.DailyFocusAgentOutput.model_validate(parsed)
    focus = daily_focus_agent.to_work_focus(answer, PERSON.user_id, workspace_host=slack_workspace.WORKSPACE_HOST)

    key_of = {slack_workspace.permalink(thread): thread.key for thread in threads}
    items = [
        {"text": item.text, "source": key_of.get(item.permalink or ""), "section": item.section}
        for item in focus.summary
    ]
    offers = [{"offer": offer.offer, "source": key_of.get(offer.source_permalink or "")} for offer in focus.suggestions]
    return {
        "person": f"<@{PERSON.user_id}>",
        "threads": [{"key": thread.key, "text": slack_workspace.text_of(thread)} for thread in threads],
        "intro": focus.intro,
        "items": items,
        "offers": offers,
        # What the code dropped is the prompt's miss even when the DM is right, so keep the count to compare runs.
        "dropped": {
            "summary": len(answer.summary) - len(focus.summary),
            "suggestions": len(answer.suggestions) - len(focus.suggestions),
        },
        "last_message": "\n".join(
            [
                focus.intro,
                *(f"- {item['section']} [{item['source']}] {item['text']}" for item in items),
                *(f"- offer [{offer['source']}] {offer['offer']}" for offer in offers),
            ]
        ),
    }


async def eval_daily_focus_agent(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        model = daily_focus_agent.AGENT_MODEL
        if task_ctx.demo_data is None:
            return {"agent_model": model, "items": [], "offers": [], "error": "No demo data team to bill the call to"}
        try:
            # Sync and blocking on the gateway, so off the event loop.
            output = await asyncio.to_thread(_ask, task_ctx.demo_data.master_team_id, case)
        except Exception as error:
            return {"agent_model": model, "items": [], "offers": [], "error": f"{type(error).__name__}: {error}"}
        return {"agent_model": model, **output}

    await OneShotEval(
        experiment_name="slack-app-daily-focus-agent",
        offline_suite=offline_suite(
            "slack_app/eval_daily_focus_agent::eval_daily_focus_agent",
            metrics=[
                "agent_covers",
                "agent_sections",
                "agent_omits_known",
                "agent_offer_recall",
                "no_reacted_offer",
                "summary_voice",
                "summary_faithful",
            ],
            suite_kind=SUITE_KIND,
        ),
        cases=CASES,
        scorers=[
            AgentCovers(),
            AgentSections(),
            AgentOmitsKnown(),
            AgentOfferRecall(),
            NoReactedOffer(),
            SummaryVoice(),
            SummaryFaithful(),
        ],
        task=task,
        ctx=ctx,
    )
