import pytest

from products.signals.backend.cursor_dispatch import (
    CURSOR_DEFAULT_MODEL,
    CursorDispatchContext,
    CursorDispatchError,
    agent_id_for_report,
    build_cursor_agent_request,
)


def _context(**overrides) -> CursorDispatchContext:
    base = {
        "repository": "PostHog/posthog",
        "title": "Checkout 500s",
        "summary": "Users hit a 500 on the checkout page",
        "report_url": "https://us.posthog.com/project/2/inbox/r1",
        "default_branch": "main",
        "priority": "P1",
        "priority_reason": "Affects revenue",
        "code_paths": ["billing/views.py"],
        "commit_hashes": ["abc123"],
    }
    base.update(overrides)
    return CursorDispatchContext(**base)


class TestBuildCursorAgentRequest:
    def test_maps_core_fields_onto_create_agent_body(self):
        body = build_cursor_agent_request(_context(), agent_id="signal-report-r1")

        assert body["repos"] == [{"url": "https://github.com/PostHog/posthog", "startingRef": "main"}]
        assert body["autoCreatePR"] is True
        assert body["agentId"] == "signal-report-r1"
        assert body["model"]["id"] == CURSOR_DEFAULT_MODEL

    def test_prompt_includes_research_context(self):
        text = build_cursor_agent_request(_context(), agent_id="x")["prompt"]["text"]

        assert "Users hit a 500 on the checkout page" in text
        assert "P1" in text
        assert "Affects revenue" in text
        assert "billing/views.py" in text
        assert "abc123" in text
        assert "https://us.posthog.com/project/2/inbox/r1" in text

    def test_mcp_attached_only_when_token_present(self):
        without_token = build_cursor_agent_request(_context(), agent_id="x")
        assert "mcpServers" not in without_token

        with_token = build_cursor_agent_request(_context(), agent_id="x", posthog_mcp_token="tok")
        assert with_token["mcpServers"][0]["name"] == "posthog"
        assert with_token["mcpServers"][0]["headers"]["Authorization"] == "Bearer tok"

    def test_full_github_url_is_passed_through(self):
        body = build_cursor_agent_request(_context(repository="https://github.com/foo/bar"), agent_id="x")
        assert body["repos"][0]["url"] == "https://github.com/foo/bar"

    def test_missing_repository_raises(self):
        with pytest.raises(CursorDispatchError):
            build_cursor_agent_request(_context(repository=None), agent_id="x")

    def test_optional_fields_omitted_cleanly(self):
        text = build_cursor_agent_request(
            _context(priority=None, priority_reason=None, code_paths=[], commit_hashes=[]),
            agent_id="x",
        )["prompt"]["text"]

        assert "Priority:" not in text
        assert "Relevant files:" not in text
        assert "Relevant commits:" not in text


def test_agent_id_for_report_is_stable_idempotency_key():
    assert agent_id_for_report("r1") == "signal-report-r1"
