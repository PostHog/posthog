"""The result shape that PostHog AI returns to an external agent, and the instructions that ask for it.

The schema becomes the task's ``json_schema``, so the agent runtime makes the final message of every
turn match it. Every field is required and no field is nullable, so the schema is valid for both the
Claude and the Codex runtimes.
"""

from typing import Any

RESULT_STATUS_COMPLETE = "complete"
RESULT_STATUS_NEEDS_INPUT = "needs_input"
RESULT_STATUS_FAILED = "failed"

_LINK = {
    "type": "object",
    "additionalProperties": False,
    "required": ["label", "url"],
    "properties": {
        "label": {"type": "string"},
        "url": {"type": "string", "description": "Empty when there is no link."},
    },
}

AGENT_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "answer", "question", "assumptions", "evidence", "artifacts", "follow_ups"],
    "properties": {
        "status": {"type": "string", "enum": [RESULT_STATUS_COMPLETE, RESULT_STATUS_NEEDS_INPUT, RESULT_STATUS_FAILED]},
        "answer": {"type": "string", "description": "The answer or plan, in Markdown."},
        "question": {
            "type": "string",
            "description": "When status is needs_input, the one question the requester must answer. Otherwise empty.",
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": _LINK, "description": "Queries, insights and replays used."},
        "artifacts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "name", "url"],
                "properties": {
                    "type": {"type": "string"},
                    "name": {"type": "string"},
                    "url": {"type": "string", "description": "Empty when there is no link."},
                },
            },
            "description": "PostHog objects created or changed, such as insights, dashboards, flags and experiments.",
        },
        "follow_ups": {"type": "array", "items": {"type": "string"}},
    },
}

AGENT_MCP_INSTRUCTIONS = """# Delegated task

Another AI agent sent this task to you through the PostHog Agent MCP, on behalf of its user. No person watches this run in real time.

- Work in this PostHog project only. Your PostHog access is limited to what the requester's key allows. If an action is refused for missing access, do not look for a workaround. Report it.
- Do the work, then end your turn with the structured result:
  - `status: complete` when the goal is done. Put the answer or plan in `answer`, in Markdown. List your assumptions, the evidence you used (with PostHog links), every PostHog object you created or changed in `artifacts`, and useful next steps.
  - `status: needs_input` only when you cannot continue without a decision from the requester. Ask one clear question in `question`, and put what you found so far in `answer`.
  - `status: failed` when the goal cannot be done. Explain why in `answer`.
- Prefer a reasonable, stated assumption to a question.
- Do not use the AskUserQuestion tool. The requester cannot see it. Ask through `status: needs_input` instead.
- A repository, when present, is for reading only. Do not change code, push branches, or open pull requests.
- The requester reads only the structured result. Put everything it needs there."""
