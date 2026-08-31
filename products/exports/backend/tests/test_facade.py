from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.user import User

from products.exports.backend.facade.api import (
    _validate_adhoc_export_context,
    get_delivery_image_url,
    render_png_export,
)
from products.exports.backend.models.exported_asset import ExportedAsset
from products.product_analytics.backend.facade.models import Insight


class TestValidateAdhocExportContext(SimpleTestCase):
    def test_accepts_insight_viz_wrapped_source(self):
        _validate_adhoc_export_context(
            {"source": {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": [{"event": "a"}]}}}
        )

    def test_accepts_data_visualization_node_over_hogql(self):
        _validate_adhoc_export_context(
            {
                "source": {
                    "kind": "DataVisualizationNode",
                    "source": {"kind": "HogQLQuery", "query": "SELECT 1"},
                    "display": "ActionsLineGraph",
                }
            }
        )

    @parameterized.expand(
        [
            ("bare_trends_query", {"source": {"kind": "TrendsQuery", "series": [{"event": "a"}]}}),
            ("data_table", {"source": {"kind": "DataTableNode"}}),
            ("non_dict_source", {"source": "SELECT 1"}),
            ("missing_source", {}),
            (
                "data_visualization_over_trends",
                {"source": {"kind": "DataVisualizationNode", "source": {"kind": "TrendsQuery"}}},
            ),
            ("data_visualization_without_source", {"source": {"kind": "DataVisualizationNode"}}),
        ]
    )
    def test_rejects_unwrapped_sources(self, _name, export_context):
        with self.assertRaises(ValueError):
            _validate_adhoc_export_context(export_context)


class TestRenderPngExportInsightLookup(BaseTest):
    def _render(self, **kwargs):
        with patch("products.exports.backend.facade.api.async_to_sync") as async_to_sync:

            def _stash_content(_coro):
                def _run():
                    asset = ExportedAsset.objects.get(team=self.team)
                    asset.content = b"png"
                    asset.save(update_fields=["content"])

                return _run

            async_to_sync.side_effect = _stash_content
            return render_png_export(team=self.team, created_by=self.user, **kwargs)

    def test_short_id_resolves_to_the_teams_insight(self):
        insight = Insight.objects.create(team=self.team, short_id="abc123xy", query={"kind": "InsightVizNode"})

        asset, png = self._render(insight_short_id=insight.short_id)

        assert asset.insight_id == insight.id
        assert png == b"png"

    @parameterized.expand(
        [
            ("unknown_short_id", {"insight_short_id": "nope0000"}),
            ("short_id_and_id", {"insight_short_id": "abc123xy", "insight_id": 1}),
        ]
    )
    def test_rejects_unresolvable_or_ambiguous_insight_selectors(self, _name, kwargs):
        with self.assertRaises(ValueError):
            render_png_export(team=self.team, created_by=self.user, **kwargs)


class TestGetDeliveryImageUrl(BaseTest):
    def test_created_by_filter_pins_the_asset_to_its_renderer(self):
        other = User.objects.create(email="other-renderer@example.com")
        asset = ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
            export_format=ExportedAsset.ExportFormat.PNG,
            content=b"png",
        )
        # No filter, or the matching renderer, mints a url. A mismatched renderer mints nothing, so a
        # cache id swapped for another same-team user's export can't be turned into a delivery url.
        assert get_delivery_image_url(team_id=self.team.id, asset_id=asset.id, expiry_delta=timedelta(days=1))
        assert get_delivery_image_url(
            team_id=self.team.id, asset_id=asset.id, expiry_delta=timedelta(days=1), created_by_id=self.user.id
        )
        assert (
            get_delivery_image_url(
                team_id=self.team.id, asset_id=asset.id, expiry_delta=timedelta(days=1), created_by_id=other.id
            )
            is None
        )


class TestAdhocRenderRequiresQueryAccess(SimpleTestCase):
    def test_a_user_without_query_access_cannot_render_an_ad_hoc_query(self):
        context = {
            "source": {
                "kind": "DataVisualizationNode",
                "source": {"kind": "HogQLQuery", "query": "SELECT 1"},
                "display": "ActionsLineGraph",
            }
        }
        with patch("products.exports.backend.facade.api.UserAccessControl") as access_control:
            access_control.return_value.check_access_level_for_resource.return_value = False
            with self.assertRaisesMessage(ValueError, "query access"):
                render_png_export(team=MagicMock(), created_by=MagicMock(), export_context=context)
