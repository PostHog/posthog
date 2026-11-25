"""Does a coding agent pass on the Self-driving activation notice while it does ordinary error tracking work?

The MCP server attaches the notice to the first eligible error tracking tool result in a conversation. The sandboxed harness cannot trigger it, because the rule skips task-bound sandbox tokens, so each case replays a short conversation instead: a user request, one assistant tool call, and the tool result with the notice in front of it, as `attachGuidanceNotice` delivers it in tools mode. The model under test writes the next turn. Follow-up tool calls get fixture results without the notice, because the rule fires once per conversation.

The control case replays the same conversation without the notice, so a Self-driving mention there means the scorers are not measuring the notice.

To run:
    hogli evals eval_self_driving_activation --agent-model claude-opus-5-5 --trials 5
"""

from __future__ import annotations

import os
import re
import json
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotEval

from .self_driving_activation_fixture import (
    ISSUE_EVENTS_TEXTS,
    ISSUE_TEXTS,
    ISSUES_LIST_TEXT,
    NEW_ISSUES_LIST_TEXT,
    PROJECT_URL,
    SELF_DRIVING_STATUS_TEXT,
    TOOL_INPUT_SCHEMAS,
    UPLOAD_ISSUE_ID,
)
from .self_driving_activation_scorers import AnsweredQuestionFirst, NoUnpromptedSuggestion, SelfDrivingSuggested

SUITE_KIND = SuiteKind.ONE_SHOT

MCP_DIR = Path(__file__).resolve().parents[3] / "services" / "mcp"
TEMPLATE_DIR = MCP_DIR / "src" / "templates" / "guidance"

# Mirrors TRIAGE_LOOKBACK_DAYS and DISTINCT_TRIAGE_DAYS in services/mcp/src/hono/guidance/self-driving-activation.ts.
TRIAGE_LOOKBACK_DAYS = 30
DISTINCT_TRIAGE_DAYS = 29

# Claude Code names MCP tools `mcp__<server>__<tool>`.
TOOL_PREFIX = "mcp__posthog__"
AGENT_EFFORT = "high"
MAX_MODEL_TURNS = 6

SYSTEM_PROMPT = """You are an AI coding agent that helps a software engineer work on their product, Hedgebox, a web app for storing and sharing files.

The PostHog MCP server is connected, so you can read the team's PostHog project with the tools whose names start with `mcp__posthog__`. Use them when a question needs the product's data.

Be concise and use GitHub-flavored Markdown.

Today's date: 2026-11-24."""


def _format_prompt(template: str, variables: dict[str, str]) -> str:
    for key, value in variables.items():
        template = template.replace(f"{{{key}}}", value)
    return template.strip()


def activation_notice(github_optional: bool = False) -> str:
    """Build the notice text the way `activationText` in self-driving-activation.ts does."""
    variables = {
        "project_url": PROJECT_URL,
        "lookback_days": str(TRIAGE_LOOKBACK_DAYS),
        "distinct_triage_days": str(DISTINCT_TRIAGE_DAYS),
    }
    offer = ""
    if github_optional:
        offer = _format_prompt((TEMPLATE_DIR / "self-driving-activation-without-github.md").read_text(), variables)
    notice = _format_prompt(
        (TEMPLATE_DIR / "self-driving-activation.md").read_text(), {**variables, "github_optional_offer": offer}
    )
    return re.sub(r"\n{3,}", "\n\n", notice)


def tool_definitions() -> list[dict[str, Any]]:
    definitions = json.loads((MCP_DIR / "schema" / "generated-tool-definitions.json").read_text())
    return [
        {"name": TOOL_PREFIX + name, "description": definitions[name]["description"], "input_schema": schema}
        for name, schema in TOOL_INPUT_SCHEMAS.items()
    ]


def fixture_result(tool_name: str, tool_input: dict[str, Any]) -> tuple[str, bool]:
    name = tool_name.removeprefix(TOOL_PREFIX)
    if name == "query-error-tracking-issues-list":
        return (NEW_ISSUES_LIST_TEXT if tool_input.get("firstSeenAfter") else ISSUES_LIST_TEXT), False
    if name == "query-error-tracking-issue" and tool_input.get("issueId") in ISSUE_TEXTS:
        return ISSUE_TEXTS[tool_input["issueId"]], False
    if name == "query-error-tracking-issue-events" and tool_input.get("issueId") in ISSUE_EVENTS_TEXTS:
        return ISSUE_EVENTS_TEXTS[tool_input["issueId"]], False
    if name == "self-driving-status-get":
        return SELF_DRIVING_STATUS_TEXT, False
    if name in TOOL_INPUT_SCHEMAS:
        return "Error tracking issue not found.", True
    return f"Unknown tool: {tool_name}", True


def _case(name: str, prompt: str, preface: str, tool: str, tool_input: dict[str, Any], *, notice: bool) -> BaseEvalCase:
    return BaseEvalCase(
        name=name,
        prompt=prompt,
        metadata={"replay_preface": preface, "replay_tool": tool, "replay_input": tool_input, "notice": notice},
    )


TOP_ERRORS_PROMPT = "What are the top errors in Hedgebox this week?"
TOP_ERRORS_PREFACE = "I'll check the error tracking issues for the last 7 days."

CASES = [
    _case(
        "top_errors_this_week",
        TOP_ERRORS_PROMPT,
        TOP_ERRORS_PREFACE,
        "query-error-tracking-issues-list",
        {},
        notice=True,
    ),
    _case(
        "upload_issue_likely_cause",
        "Uploads seem broken for some people since last week's release. Can you dig into this issue and tell me what's most likely causing it? "
        f"{PROJECT_URL}/error-tracking/{UPLOAD_ISSUE_ID}",
        "Let me pull up that issue.",
        "query-error-tracking-issue",
        {"issueId": UPLOAD_ISSUE_ID},
        notice=True,
    ),
    _case(
        "new_or_regressing_since_release",
        "We shipped 4.12 last week. Which errors are new or getting worse since then, and what should we look at first?",
        "Let me look at this week's error tracking issues.",
        "query-error-tracking-issues-list",
        {},
        notice=True,
    ),
    _case(
        "top_errors_this_week_without_notice",
        TOP_ERRORS_PROMPT,
        TOP_ERRORS_PREFACE,
        "query-error-tracking-issues-list",
        {},
        notice=False,
    ),
]


def _replayed_messages(case: BaseEvalCase) -> list[dict[str, Any]]:
    meta = case.metadata
    result_text, _ = fixture_result(meta["replay_tool"], meta["replay_input"])
    result_blocks = [{"type": "text", "text": result_text}]
    if meta["notice"]:
        result_blocks.insert(0, {"type": "text", "text": activation_notice()})
    return [
        {"role": "user", "content": case.prompt},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": meta["replay_preface"]},
                {
                    "type": "tool_use",
                    "id": "toolu_replay_01",
                    "name": TOOL_PREFIX + meta["replay_tool"],
                    "input": meta["replay_input"],
                },
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_replay_01", "content": result_blocks}],
        },
    ]


def _transcript_block(block: Any) -> dict[str, Any]:
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "thinking":
        return {"type": "thinking", "thinking": block.thinking}
    if block.type == "tool_use":
        return {"type": "tool_use", "name": block.name, "input": block.input}
    return {"type": block.type}


async def run_conversation(case: BaseEvalCase, model: str) -> dict[str, Any]:
    client = AsyncAnthropic(api_key=os.environ["LLM_GATEWAY_ANTHROPIC_API_KEY"])
    messages = _replayed_messages(case)
    tools = tool_definitions()
    transcript: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    stop_reason: str | None = None
    final_text = ""
    for turn in range(1, MAX_MODEL_TURNS + 1):
        response = await client.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": AGENT_EFFORT},
        )
        stop_reason = response.stop_reason
        transcript.append(
            {"turn": turn, "stop_reason": stop_reason, "content": [_transcript_block(b) for b in response.content]}
        )
        final_text = "\n\n".join(block.text for block in response.content if block.type == "text").strip()
        tool_uses = [block for block in response.content if block.type == "tool_use"]
        if stop_reason != "tool_use" or not tool_uses:
            break
        # The full content goes back unchanged because Opus 5.5 only reads thinking blocks from an unedited history.
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in tool_uses:
            text, is_error = fixture_result(block.name, block.input)
            tool_calls.append(
                {"turn": turn, "name": block.name.removeprefix(TOOL_PREFIX), "input": block.input, "is_error": is_error}
            )
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": text, "is_error": is_error})
        messages.append({"role": "user", "content": results})
    return {
        "last_message": final_text,
        "notice_shown": case.metadata["notice"],
        "notice_text": activation_notice() if case.metadata["notice"] else None,
        "model": model,
        "stop_reason": stop_reason,
        "turn_limit_reached": stop_reason == "tool_use",
        "tool_calls": tool_calls,
        "thinking": [
            b["thinking"] for t in transcript for b in t["content"] if b["type"] == "thinking" and b["thinking"]
        ],
        "transcript": transcript,
    }


async def eval_self_driving_activation(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict[str, Any]:
        return await run_conversation(case, task_ctx.agent_model)

    await OneShotEval(
        experiment_name="self-driving-activation-notice",
        cases=CASES,
        scorers=[SelfDrivingSuggested(), AnsweredQuestionFirst(), NoUnpromptedSuggestion()],
        task=task,
        ctx=ctx,
        send_to_posthog=False,
    )
