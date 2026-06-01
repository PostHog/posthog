from posthog.test.base import APIBaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import ActionConversionGoal

from products.web_analytics.backend.attribution import AttributionFinding, AttributionResult
from products.web_analytics.backend.max_tools import InvestigateWebAnalyticsTool

from ee.hogai.utils.types import AssistantState

_BUILD_DIGEST_PATH = "products.web_analytics.backend.max_tools.build_digest_from_spec"
_ATTRIBUTION_PATH = "products.web_analytics.backend.max_tools.attribute_change"

_FAKE_DIGEST = {
    "visitors": {"current": 9840, "previous": 12240, "change": None},
    "bounce_rate": {"current": 42.0, "previous": 40.0, "change": None},
    "pageviews": {"current": 5000, "previous": 4800, "change": None},
    "top_pages": [{"path": "/pricing", "visitors": 320}],
    "top_sources": [{"name": "google.com", "visitors": 450}],
    "goals": [],
}


def _attribution() -> AttributionResult:
    driver = AttributionFinding(
        dimension="channel",
        segment="Organic Search",
        current=4100,
        previous=6200,
        delta=-2100,
        contribution_pct=87.5,
    )
    return AttributionResult(
        metric="visitors",
        overall_current=9840,
        overall_previous=12240,
        overall_delta=-2400,
        primary_driver=driver,
        per_dimension=[driver],
    )


class TestInvestigateWebAnalyticsTool(APIBaseTest):
    def _create_tool(self, filters: dict | None = None) -> InvestigateWebAnalyticsTool:
        config: RunnableConfig = {"configurable": {}}
        if filters is not None:
            config["configurable"]["contextual_tools"] = {"investigate_web_analytics": {"filters": filters}}
        return InvestigateWebAnalyticsTool(
            team=self.team, user=self.user, state=AssistantState(messages=[]), config=config
        )

    def test_declares_web_analytics_viewer_access(self):
        assert self._create_tool().get_required_resource_access() == [("web_analytics", "viewer")]

    async def test_resolves_spec_from_context(self):
        tool = self._create_tool(
            filters={"date_from": "-30d", "filter_test_accounts": False, "conversion_goal": {"actionId": 42}}
        )
        with (
            patch(_BUILD_DIGEST_PATH, return_value=_FAKE_DIGEST) as mock_build,
            patch(_ATTRIBUTION_PATH, return_value=None),
        ):
            content, artifact = await tool._arun_impl()

        spec = mock_build.call_args.args[1]
        assert spec.date_range.date_from == "-30d"
        assert spec.filter_test_accounts is False
        assert isinstance(spec.conversion_goal, ActionConversionGoal)
        assert "GitHub-flavored markdown" in content
        assert artifact["digest"] == _FAKE_DIGEST

    async def test_renders_attribution(self):
        tool = self._create_tool()
        attribution = _attribution()
        with (
            patch(_BUILD_DIGEST_PATH, return_value=_FAKE_DIGEST),
            patch(_ATTRIBUTION_PATH, return_value=attribution),
        ):
            content, artifact = await tool._arun_impl()

        assert "Change attribution" in content
        assert "`Organic Search`" in content
        assert "87.5% of the change" in content
        assert artifact["attribution"]["primary_driver"]["segment"] == "Organic Search"
        assert "recordings_filter" not in artifact

    async def test_survives_attribution_failure(self):
        tool = self._create_tool()
        with (
            patch(_BUILD_DIGEST_PATH, return_value=_FAKE_DIGEST),
            patch(_ATTRIBUTION_PATH, return_value=None),
        ):
            content, artifact = await tool._arun_impl()

        assert "GitHub-flavored markdown" in content
        assert artifact["digest"] == _FAKE_DIGEST
        assert artifact["attribution"] is None
