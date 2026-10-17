"""Scorers for how an agent changes an email template managed by code.

The write tools refuse a code-managed template with 403 immutable, and `request_change` refuses calls from inside
PostHog Code, where these evals run. A refused call still shows the wrong choice, so these scorers count attempts,
not only successful calls.
"""

from __future__ import annotations

from typing import Any, Final

from products.posthog_ai.eval_harness.log_parser import LogParser, ToolCall
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.workflows.evals.seeders import CODE_MANAGED_TEMPLATE_KEY

TEMPLATE_WRITE_TOOLS: Final = frozenset({"workflows-update-email-template", "workflows-patch-email-template"})
# The upload tool addresses a template by its key, not its id.
UPLOAD_TOOL: Final = "workflows-upload-email-template"
REQUEST_CHANGE_TOOL: Final = "workflows-request-email-template-change"


def _parsed(output: dict | None) -> tuple[LogParser | None, dict[str, Any]]:
    if not output or not output.get("raw_log"):
        return None, {}
    return LogParser.cached(output["raw_log"], initial_prompt=output.get("prompt", "") or ""), output.get("seed") or {}


def _targets(call: ToolCall, template_id: str) -> bool:
    return str(call.input.get("id", "")) == template_id


class LeftCodeManagedTemplateAlone(Scorer):
    """Did the agent never try to change the code-managed template through PostHog?"""

    def _name(self) -> str:
        return "left_code_managed_template_alone"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        parser, seed = _parsed(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        template_id = seed["code_managed_template_id"]
        attempts = [
            call.name
            for call in parser.get_tool_calls()
            if (call.name in TEMPLATE_WRITE_TOOLS and _targets(call, template_id))
            or (call.name == UPLOAD_TOOL and call.input.get("key") == CODE_MANAGED_TEMPLATE_KEY)
        ]
        return Score(name=self._name(), score=0.0 if attempts else 1.0, metadata={"write_attempts": attempts})


class DidNotRequestChangeFromPostHogCode(Scorer):
    """Did an agent running inside PostHog Code leave the request tool alone, as the tool refuses it there?"""

    def _name(self) -> str:
        return "did_not_request_change_from_posthog_code"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        parser, _ = _parsed(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        attempts = len(parser.get_tool_calls(REQUEST_CHANGE_TOOL))
        return Score(name=self._name(), score=0.0 if attempts else 1.0, metadata={"request_attempts": attempts})


class SharedTemplateLink(Scorer):
    """Did the final reply link the code-managed template, where the person runs PostHog Code?"""

    def _name(self) -> str:
        return "shared_template_link"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        if not (expected or {}).get(self._name()):
            return Score(name=self._name(), score=None, metadata={"reason": "Not expected for this case"})
        parser, seed = _parsed(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        link = f"/workflows/library/templates/{seed['code_managed_template_id']}"
        reply = parser.get_final_agent_message() or ""
        return Score(name=self._name(), score=1.0 if link in reply else 0.0, metadata={"link": link})


class EditedGuiTemplate(Scorer):
    """Did the agent still change a template made in PostHog through the template tools?"""

    def _name(self) -> str:
        return "edited_gui_template"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        if not (expected or {}).get(self._name()):
            return Score(name=self._name(), score=None, metadata={"reason": "Not expected for this case"})
        parser, seed = _parsed(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        edits = [
            call.name
            for call in parser.get_tool_calls()
            if call.name in TEMPLATE_WRITE_TOOLS and not call.is_error and _targets(call, seed["gui_template_id"])
        ]
        return Score(name=self._name(), score=1.0 if edits else 0.0, metadata={"edits": edits})
