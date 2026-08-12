from django.test import SimpleTestCase

from parameterized import parameterized

from products.exports.backend.facade.api import _validate_adhoc_export_context


class TestValidateAdhocExportContext(SimpleTestCase):
    def test_accepts_insight_viz_wrapped_source(self):
        _validate_adhoc_export_context(
            {"source": {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": [{"event": "a"}]}}}
        )

    @parameterized.expand(
        [
            ("bare_trends_query", {"source": {"kind": "TrendsQuery", "series": [{"event": "a"}]}}),
            ("data_table", {"source": {"kind": "DataTableNode"}}),
            ("non_dict_source", {"source": "SELECT 1"}),
            ("missing_source", {}),
        ]
    )
    def test_rejects_unwrapped_sources(self, _name, export_context):
        with self.assertRaises(ValueError):
            _validate_adhoc_export_context(export_context)
