from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.exports.backend.facade.api import _validate_adhoc_export_context, render_png_export


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
