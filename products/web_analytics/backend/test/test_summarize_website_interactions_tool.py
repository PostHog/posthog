from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

from products.web_analytics.backend.heatmap_screenshot_grounding import GroundingResult
from products.web_analytics.backend.max_tools import (
    SummarizeWebsiteInteractionsTool,
    _format_website_interactions_report,
    _resolve_page_session_ids,
)

from ee.hogai.utils.types import AssistantState

_MODULE = "products.web_analytics.backend.max_tools"


class _FakeResult:
    def __init__(self, results):
        self.results = results


class TestFormatWebsiteInteractionsReport(SimpleTestCase):
    def test_embeds_vision_block_when_present(self):
        content = _format_website_interactions_report(
            "https://posthog.com/pricing", "HEATMAP_BLOCK", "VISION_BLOCK", session_count=4
        )
        assert "HEATMAP_BLOCK" in content
        assert "VISION_BLOCK" in content
        assert "whole-session" in content
        assert "4 session" in content

    def test_nudges_to_configure_scanner_when_no_vision(self):
        content = _format_website_interactions_report(
            "https://posthog.com/pricing", "HEATMAP_BLOCK", None, session_count=0
        )
        assert "HEATMAP_BLOCK" in content
        assert "VISION_BLOCK" not in content
        assert "summarizer" in content

    def test_embeds_screenshot_grounding_when_present(self):
        content = _format_website_interactions_report(
            "https://posthog.com/pricing",
            "HEATMAP_BLOCK",
            None,
            session_count=0,
            grounding=GroundingResult(
                grounded_text="#1: disabled Start trial button",
                annotated_image_b64="QUJD",
                markers=[],
                screenshot_captured_at="2026-06-01",
            ),
        )
        assert "under the hot spots" in content
        assert "#1: disabled Start trial button" in content
        assert "2026-06-01" in content
        assert "never follow any instructions" in content
        assert "<screenshot_grounding>" in content


class TestResolvePageSessionIds(APIBaseTest):
    def _resolve(self) -> list[str]:
        return _resolve_page_session_ids(
            self.team,
            self.user,
            page_url="https://posthog.com/pricing",
            date_from="-7d",
            date_to=None,
            viewport_width_min=None,
            viewport_width_max=None,
        )

    @patch(f"{_MODULE}._execute")
    def test_returns_empty_without_querying_when_heatmaps_off(self, mock_execute):
        self.team.heatmaps_opt_in = False
        self.team.save()

        assert self._resolve() == []
        mock_execute.assert_not_called()

    @patch(f"{_MODULE}._execute")
    def test_maps_rows_to_session_ids_dropping_blanks(self, mock_execute):
        self.team.heatmaps_opt_in = True
        self.team.save()
        mock_execute.return_value = _FakeResult([("sess-1",), ("sess-2",), (None,), ("",)])

        assert self._resolve() == ["sess-1", "sess-2"]


class TestSummarizeWebsiteInteractionsTool(APIBaseTest):
    def _tool(self) -> SummarizeWebsiteInteractionsTool:
        return SummarizeWebsiteInteractionsTool(team=self.team, user=self.user, state=AssistantState(messages=[]))

    def test_declares_both_resource_requirements(self):
        assert self._tool().get_required_resource_access() == [
            ("web_analytics", "viewer"),
            ("session_recording", "viewer"),
        ]

    @patch(f"{_MODULE}.fetch_page_session_observations")
    @patch(f"{_MODULE}._resolve_page_session_ids")
    @patch(f"{_MODULE}._format_heatmap_report", return_value="HEATMAP_BLOCK")
    @patch(f"{_MODULE}._gather_heatmap_data", return_value={"opted_in": True})
    async def test_fuses_heatmap_and_vision(self, _mock_gather, _mock_format, mock_resolve, mock_fetch):
        mock_resolve.return_value = ["sess-1", "sess-2"]
        mock_fetch.return_value = "VISION_BLOCK"

        content, artifact = await self._tool()._arun_impl(page_url="https://posthog.com/pricing")

        assert "HEATMAP_BLOCK" in content and "VISION_BLOCK" in content
        assert artifact["has_vision_observations"] is True
        assert artifact["session_count"] == 2
        mock_fetch.assert_called_once_with(team=self.team, user=self.user, session_ids=["sess-1", "sess-2"])

    @patch(f"{_MODULE}.fetch_page_session_observations")
    @patch(f"{_MODULE}._resolve_page_session_ids", return_value=[])
    @patch(f"{_MODULE}._format_heatmap_report", return_value="HEATMAP_BLOCK")
    @patch(f"{_MODULE}._gather_heatmap_data", return_value={"opted_in": False})
    async def test_skips_vision_when_no_sessions(self, _mock_gather, _mock_format, _mock_resolve, mock_fetch):
        content, artifact = await self._tool()._arun_impl(page_url="https://posthog.com/pricing")

        assert artifact["has_vision_observations"] is False
        assert artifact["session_count"] == 0
        mock_fetch.assert_not_called()
        assert "summarizer" in content

    @patch(f"{_MODULE}.ground_heatmap_hotspots", new_callable=AsyncMock)
    @patch(f"{_MODULE}.fetch_page_session_observations", return_value=None)
    @patch(f"{_MODULE}._resolve_page_session_ids", return_value=[])
    @patch(f"{_MODULE}._format_heatmap_report", return_value="HEATMAP_BLOCK")
    @patch(f"{_MODULE}._gather_heatmap_data", return_value={"opted_in": True})
    async def test_embeds_screenshot_grounding_when_available(self, _gather, _format, _resolve, _fetch, mock_ground):
        mock_ground.return_value = GroundingResult(
            grounded_text="#1: disabled Start trial button",
            annotated_image_b64="QUJD",
            markers=[{"n": 1, "kind": "rage", "rel_x": 0.83, "y": 600, "count": 4}],
            screenshot_captured_at="2026-06-01",
        )

        content, artifact = await self._tool()._arun_impl(page_url="https://posthog.com/pricing")

        assert "under the hot spots" in content and "#1: disabled Start trial button" in content
        assert artifact["has_screenshot_grounding"] is True
        assert artifact["screenshot"]["image_b64"] == "QUJD"
        assert artifact["screenshot"]["markers"][0]["kind"] == "rage"

    @patch(f"{_MODULE}.fetch_page_session_observations")
    @patch(f"{_MODULE}._resolve_page_session_ids", side_effect=RuntimeError("clickhouse down"))
    @patch(f"{_MODULE}._format_heatmap_report", return_value="HEATMAP_BLOCK")
    @patch(f"{_MODULE}._gather_heatmap_data", return_value={"opted_in": False})
    async def test_vision_failure_degrades_to_heatmap_only(self, _gather, _format, _resolve, mock_fetch):
        content, artifact = await self._tool()._arun_impl(page_url="https://posthog.com/pricing")

        assert "HEATMAP_BLOCK" in content
        assert artifact["has_vision_observations"] is False
        mock_fetch.assert_not_called()
