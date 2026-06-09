from posthog.test.base import APIBaseTest
from unittest.mock import patch

from products.web_analytics.backend.max_tools import AssessHeatmapTool

from ee.hogai.utils.types import AssistantState


class _FakeResult:
    def __init__(self, results):
        self.results = results


class TestAssessHeatmapTool(APIBaseTest):
    def _create_tool(self) -> AssessHeatmapTool:
        return AssessHeatmapTool(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
        )

    def _opt_in(self) -> None:
        self.team.heatmaps_opt_in = True
        self.team.save()

    def test_declares_web_analytics_viewer_access(self):
        tool = self._create_tool()
        assert tool.get_required_resource_access() == [("web_analytics", "viewer")]

    async def test_reports_when_heatmaps_not_opted_in(self):
        self.team.heatmaps_opt_in = False
        await self.team.asave()

        tool = self._create_tool()
        content, artifact = await tool._arun_impl(page_url="https://posthog.com/pricing")

        assert artifact == {"opted_in": False}
        assert "aren't enabled" in content
        assert "heatmaps_opt_in" in content

    @patch("products.web_analytics.backend.max_tools._execute")
    async def test_formats_full_report(self, mock_execute):
        self._opt_in()
        # Calls happen in this order: click coords, click fold, rageclick coords, scroll buckets, autocapture.
        mock_execute.side_effect = [
            _FakeResult([(False, 0.5, 220, 100), (False, 0.2, 80, 40)]),
            _FakeResult([(120, 42, 600)]),
            _FakeResult([(False, 0.8, 300, 12)]),
            _FakeResult([(0, 50, 100), (100, 30, 50), (200, 20, 20)]),
            _FakeResult([("Pricing", "a.nav-link", 80), ("Read the docs", "span", 20)]),
        ]

        tool = self._create_tool()
        content, artifact = await tool._arun_impl(page_url="https://posthog.com/pricing")

        # Fold split is the headline layout signal.
        assert "35.0% of clicks landed below the fold" in content
        assert "~600px" in content
        # Rage clicks called out.
        assert "12 rage-click interaction(s)" in content
        # Top hotspot surfaced.
        assert "100× at x≈0.5, y≈220px" in content
        # Autocapture identity included.
        assert '"Pricing"' in content
        # Scroll reach summarised.
        assert "Scroll reach" in content

        assert artifact["opted_in"] is True
        assert len(artifact["clicks"]) == 2
        assert artifact["clicks"][0]["count"] == 100
        assert artifact["fold"]["pct_below_fold"] == 35.0
        assert artifact["rageclicks"][0]["count"] == 12
        assert artifact["elements"][0]["text"] == "Pricing"

    @patch("products.web_analytics.backend.max_tools._execute")
    async def test_reports_no_interactions(self, mock_execute):
        self._opt_in()
        mock_execute.side_effect = [
            _FakeResult([]),  # clicks
            _FakeResult([(0, 0, None)]),  # fold (empty)
            _FakeResult([]),  # rageclicks
            _FakeResult([]),  # scrolldepth
            _FakeResult([]),  # autocapture
        ]

        tool = self._create_tool()
        content, _artifact = await tool._arun_impl(page_url="https://posthog.com/unknown")

        assert "No heatmap interactions matched this page" in content

    @patch("products.web_analytics.backend.max_tools._execute")
    async def test_no_rage_clicks_is_called_out_positively(self, mock_execute):
        self._opt_in()
        mock_execute.side_effect = [
            _FakeResult([(False, 0.5, 220, 100)]),  # clicks
            _FakeResult([(100, 10, 600)]),  # fold
            _FakeResult([]),  # rageclicks — none
            _FakeResult([(0, 50, 50)]),  # scrolldepth
            _FakeResult([("Pricing", "a", 80)]),  # autocapture
        ]

        tool = self._create_tool()
        content, _artifact = await tool._arun_impl(page_url="https://posthog.com/pricing")

        assert "None detected" in content
