from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models.health_issue import HealthIssue

from products.web_analytics.backend.max_tools import WebAnalyticsDoctorTool

from ee.hogai.utils.types import AssistantState


class TestWebAnalyticsDoctorTool(APIBaseTest):
    def _create_tool(self) -> WebAnalyticsDoctorTool:
        return WebAnalyticsDoctorTool(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
        )

    def test_declares_web_analytics_viewer_access(self):
        tool = self._create_tool()
        assert tool.get_required_resource_access() == [("web_analytics", "viewer")]

    @patch("products.web_analytics.backend.max_tools._process_batch_detection")
    async def test_reports_healthy_when_no_issues(self, _mock_process):
        tool = self._create_tool()

        content, artifact = await tool._arun_impl()

        assert "looks healthy" in content
        assert artifact["issues"] == []
        assert artifact["failed_kinds"] == []
        # Registry must have populated with web-analytics kinds — proves the import side effect worked.
        assert "reverse_proxy" in artifact["ran_kinds"]
        assert "partial_proxy" in artifact["ran_kinds"]
        assert "authorized_urls" in artifact["ran_kinds"]

    @patch("products.web_analytics.backend.max_tools._process_batch_detection")
    async def test_returns_active_issues_sorted_by_severity(self, _mock_process):
        await HealthIssue.objects.acreate(
            team_id=self.team.id,
            kind="reverse_proxy",
            severity=HealthIssue.Severity.WARNING,
            payload={"reason": "No reverse proxy detected."},
            unique_hash="hash-reverse-proxy",
        )
        await HealthIssue.objects.acreate(
            team_id=self.team.id,
            kind="no_live_events",
            severity=HealthIssue.Severity.CRITICAL,
            payload={"reason": "No pageview or screen events detected."},
            unique_hash="hash-no-live",
        )

        tool = self._create_tool()
        content, artifact = await tool._arun_impl()

        assert "Found **2** active Web Analytics issue(s)" in content
        critical_pos = content.find("no_live_events")
        warning_pos = content.find("reverse_proxy")
        assert critical_pos != -1 and warning_pos != -1
        assert critical_pos < warning_pos, "critical issues should be listed before warnings"

        kinds = {i["kind"] for i in artifact["issues"]}
        assert kinds == {"reverse_proxy", "no_live_events"}

    @patch("products.web_analytics.backend.max_tools._process_batch_detection")
    async def test_renders_partial_proxy_host_lists(self, _mock_process):
        await HealthIssue.objects.acreate(
            team_id=self.team.id,
            kind="partial_proxy",
            severity=HealthIssue.Severity.WARNING,
            payload={
                "reason": "Reverse proxy is only configured on some hostnames.",
                "proxied_hosts": ["app.example.com"],
                "unproxied_hosts": ["www.example.com"],
            },
            unique_hash="hash-partial-proxy",
        )

        tool = self._create_tool()
        content, _artifact = await tool._arun_impl()

        assert "proxied hosts: app.example.com" in content
        assert "unproxied hosts: www.example.com" in content

    @patch("products.web_analytics.backend.max_tools._process_batch_detection")
    async def test_isolates_per_kind_failures(self, mock_process):
        def selective_raiser(*, team_ids, kind, detect_fn):
            if kind == "reverse_proxy":
                raise RuntimeError("clickhouse went away")

        mock_process.side_effect = selective_raiser

        tool = self._create_tool()
        content, artifact = await tool._arun_impl()

        assert "reverse_proxy" in artifact["failed_kinds"]
        assert "no_live_events" in artifact["ran_kinds"]
        assert "could not be re-evaluated" in content

    @patch("products.web_analytics.backend.max_tools._process_batch_detection")
    async def test_ignores_issues_from_other_teams(self, _mock_process):
        other_team = await self.organization.teams.acreate(name="other team")
        await HealthIssue.objects.acreate(
            team_id=other_team.id,
            kind="reverse_proxy",
            severity=HealthIssue.Severity.WARNING,
            payload={"reason": "Not my team's problem."},
            unique_hash="hash-other-team",
        )

        tool = self._create_tool()
        content, artifact = await tool._arun_impl()

        assert artifact["issues"] == []
        assert "looks healthy" in content

    @patch("products.web_analytics.backend.max_tools._process_batch_detection")
    async def test_ignores_resolved_and_dismissed_issues(self, _mock_process):
        await HealthIssue.objects.acreate(
            team_id=self.team.id,
            kind="reverse_proxy",
            severity=HealthIssue.Severity.WARNING,
            payload={"reason": "Old resolved issue."},
            unique_hash="hash-resolved",
            status=HealthIssue.Status.RESOLVED,
        )
        await HealthIssue.objects.acreate(
            team_id=self.team.id,
            kind="scroll_depth",
            severity=HealthIssue.Severity.WARNING,
            payload={"reason": "Dismissed issue."},
            unique_hash="hash-dismissed",
            dismissed=True,
        )

        tool = self._create_tool()
        _content, artifact = await tool._arun_impl()

        assert artifact["issues"] == []
