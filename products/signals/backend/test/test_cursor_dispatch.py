import json

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from products.signals.backend.cursor_dispatch import (
    CURSOR_AGENTS_API_URL,
    CursorDispatchContext,
    CursorDispatchError,
    agent_id_for_report,
    build_cursor_agent_request,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact


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
        assert "model" not in body

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
    assert agent_id_for_report("r1") == "bc-r1"


FLAG_PATH = "products.signals.backend.views.posthoganalytics.feature_enabled"
POST_PATH = "products.signals.backend.cursor_dispatch.requests.post"


class TestDispatchToCursorEndpoint(APIBaseTest):
    def _url(self, report_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report_id}/dispatch_to_cursor/"

    def _create_report(self, *, with_repo: bool = True) -> SignalReport:
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout 500s",
            summary="Users hit a 500 on the checkout page",
            signal_count=3,
            total_weight=1.5,
        )
        if with_repo:
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.REPO_SELECTION,
                content=json.dumps({"repository": "PostHog/posthog", "reason": "matches the stack trace"}),
            )
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=json.dumps({"priority": "P1", "explanation": "Affects revenue"}),
        )
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING,
            content=json.dumps(
                {
                    "signal_id": "s1",
                    "relevant_code_paths": ["billing/views.py"],
                    "relevant_commit_hashes": {"abc123": "introduced the bug"},
                    "verified": True,
                }
            ),
        )
        return report

    def test_flag_off_returns_404(self):
        report = self._create_report()
        with patch(FLAG_PATH, return_value=False):
            response = self.client.post(self._url(str(report.id)))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_flag_on_but_no_key_returns_409(self):
        report = self._create_report()
        with patch(FLAG_PATH, return_value=True), self.settings(CURSOR_API_KEY=""):
            response = self.client.post(self._url(str(report.id)))
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_report_without_repository_returns_502(self):
        report = self._create_report(with_repo=False)
        with (
            patch(FLAG_PATH, return_value=True),
            self.settings(CURSOR_API_KEY="test-key"),
            patch(POST_PATH) as mock_post,
        ):
            response = self.client.post(self._url(str(report.id)))
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        mock_post.assert_not_called()

    def test_dispatch_posts_to_cursor_and_returns_agent(self):
        report = self._create_report()
        cursor_response = MagicMock(status_code=200)
        cursor_response.json.return_value = {
            "id": "agent_123",
            "url": "https://cursor.com/agents/agent_123",
            "status": "queued",
        }

        with (
            patch(FLAG_PATH, return_value=True),
            self.settings(CURSOR_API_KEY="test-key"),
            patch(POST_PATH, return_value=cursor_response) as mock_post,
        ):
            response = self.client.post(self._url(str(report.id)))

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "agent_id": "agent_123",
            "agent_url": "https://cursor.com/agents/agent_123",
            "agent_status": "queued",
        }

        mock_post.assert_called_once()
        call = mock_post.call_args
        assert call.args[0] == CURSOR_AGENTS_API_URL
        assert call.kwargs["headers"]["Authorization"] == "Bearer test-key"

        body = call.kwargs["json"]
        assert body["repos"] == [{"url": "https://github.com/PostHog/posthog", "startingRef": "main"}]
        assert body["autoCreatePR"] is True
        assert body["agentId"] == f"bc-{report.id}"
        prompt_text = body["prompt"]["text"]
        assert "Users hit a 500 on the checkout page" in prompt_text
        assert "P1" in prompt_text
        assert "billing/views.py" in prompt_text
        assert "abc123" in prompt_text
