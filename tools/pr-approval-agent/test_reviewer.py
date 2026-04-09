"""Tests for reviewer fallback behavior."""

import sys
import types
from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_reviewer_module(monkeypatch, *, posthog_query_factory):
    call_order: list[str] = []

    class ClaudeAgentOptions:
        def __init__(self, **kwargs):
            self.system_prompt = kwargs.get("system_prompt")
            self.allowed_tools = kwargs.get("allowed_tools")
            self.disallowed_tools = kwargs.get("disallowed_tools")
            self.cwd = kwargs.get("cwd")
            self.max_turns = kwargs.get("max_turns")
            self.model = kwargs.get("model")
            self.permission_mode = kwargs.get("permission_mode")
            self.output_format = kwargs.get("output_format")
            self.effort = kwargs.get("effort")
            self.extra_args = kwargs.get("extra_args")
            self.include_partial_messages = kwargs.get("include_partial_messages", False)

    class ResultMessage:
        def __init__(self, structured_output=None, subtype=None):
            self.structured_output = structured_output
            self.subtype = subtype

    class AssistantMessage:
        def __init__(self, content=None):
            self.content = content or []

    class ToolUseBlock:
        def __init__(self, name="", input=None):
            self.name = name
            self.input = input or {}

    async def base_query(*, prompt, options, transport=None):
        call_order.append("plain")
        yield ResultMessage(
            structured_output={
                "verdict": "APPROVE",
                "reasoning": "No showstoppers, low-risk fix.",
                "risk": "low",
                "issues": [],
            }
        )

    claude_agent_sdk = types.ModuleType("claude_agent_sdk")
    claude_agent_sdk.ClaudeAgentOptions = ClaudeAgentOptions
    claude_agent_sdk.ResultMessage = ResultMessage
    claude_agent_sdk.query = base_query

    claude_agent_sdk_types = types.ModuleType("claude_agent_sdk.types")
    claude_agent_sdk_types.AssistantMessage = AssistantMessage
    claude_agent_sdk_types.ToolUseBlock = ToolUseBlock

    @dataclass
    class PRData:
        number: int
        repo: str
        title: str
        state: str
        draft: bool
        mergeable_state: str
        author: str
        labels: list[str]
        base_sha: str
        head_sha: str
        files: list[dict]
        reviews: list[dict]
        review_comments: list[dict]
        check_runs: list[dict]

        @property
        def lines_added(self) -> int:
            return sum(f["additions"] for f in self.files)

        @property
        def lines_deleted(self) -> int:
            return sum(f["deletions"] for f in self.files)

        @property
        def lines_total(self) -> int:
            return self.lines_added + self.lines_deleted

    github_module = types.ModuleType("github")
    github_module.PRData = PRData

    monkeypatch.setitem(sys.modules, "claude_agent_sdk", claude_agent_sdk)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk.types", claude_agent_sdk_types)
    monkeypatch.setitem(sys.modules, "github", github_module)

    if posthog_query_factory is not None:
        posthoganalytics_module = types.ModuleType("posthoganalytics")
        posthoganalytics_ai_module = types.ModuleType("posthoganalytics.ai")
        posthoganalytics_claude_module = types.ModuleType("posthoganalytics.ai.claude_agent_sdk")
        posthoganalytics_claude_module.query = posthog_query_factory(call_order, ResultMessage)
        monkeypatch.setitem(sys.modules, "posthoganalytics", posthoganalytics_module)
        monkeypatch.setitem(sys.modules, "posthoganalytics.ai", posthoganalytics_ai_module)
        monkeypatch.setitem(sys.modules, "posthoganalytics.ai.claude_agent_sdk", posthoganalytics_claude_module)
    else:
        monkeypatch.delitem(sys.modules, "posthoganalytics.ai.claude_agent_sdk", raising=False)
        monkeypatch.delitem(sys.modules, "posthoganalytics.ai", raising=False)
        monkeypatch.delitem(sys.modules, "posthoganalytics", raising=False)

    reviewer_path = Path(__file__).with_name("reviewer.py")
    spec = spec_from_file_location("reviewer_under_test", reviewer_path)
    module = module_from_spec(spec)
    assert spec and spec.loader
    monkeypatch.setitem(sys.modules, "reviewer_under_test", module)
    spec.loader.exec_module(module)
    return module, PRData, call_order


def test_reviewer_falls_back_to_plain_sdk_when_posthog_wrapper_requires_api_key(monkeypatch, tmp_path) -> None:
    def failing_posthog_query_factory(call_order, _result_message_class):
        async def failing_posthog_query(*, prompt, options, **kwargs):
            call_order.append("posthog")
            raise RuntimeError("API key is required")
            yield

        return failing_posthog_query

    reviewer_module, pr_data_class, call_order = _load_reviewer_module(
        monkeypatch, posthog_query_factory=failing_posthog_query_factory
    )

    diff_path = tmp_path / "diff.patch"
    diff_path.write_text("")
    monkeypatch.setattr(reviewer_module.Reviewer, "_write_diff_file", lambda self, pr: diff_path)

    reviewer = reviewer_module.Reviewer(tmp_path)
    pr = pr_data_class(
        number=53945,
        repo="PostHog/posthog",
        title="fix(surveys): default new survey to guided wizard",
        state="OPEN",
        draft=False,
        mergeable_state="MERGEABLE",
        author="lucasheriques",
        labels=[],
        base_sha="base",
        head_sha="head",
        files=[
            {"filename": "frontend/src/scenes/surveys/wizard/SurveyWizard.test.tsx", "additions": 5, "deletions": 1}
        ],
        reviews=[],
        review_comments=[],
        check_runs=[],
    )

    result = reviewer.review(
        pr,
        {"tier": "T1-agent", "t1_subclass": "T1b-small", "breadth": "single-area", "commit_type": "fix"},
        {"gate_verdict": "ALLOWED", "gates": []},
    )

    assert result["verdict"] == "APPROVE"
    assert result["reasoning"] == "No showstoppers, low-risk fix."
    assert result["risk"] == "low"
    assert result["issues"] == []
    assert result["fallback_debug_summary"].startswith(
        "PostHog Claude instrumentation failed before review started; fell back to plain Claude SDK. "
        "error=RuntimeError: API key is required."
    )
    assert call_order == ["posthog", "plain"]
