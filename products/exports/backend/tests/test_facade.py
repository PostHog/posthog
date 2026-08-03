from datetime import timedelta

from django.test import SimpleTestCase
from django.utils.timezone import now

from parameterized import parameterized

from products.exports.backend.facade.api import (
    DATASET_EXPORT_KIND,
    JSONL_EXPORT_FORMAT,
    STUCK_EXPORT_MESSAGE,
    _validate_adhoc_export_context,
    get_export_asset_effective_exception,
    get_export_asset_status,
)
from products.exports.backend.models.exported_asset import ExportedAsset


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


class TestExportAssetStatus(SimpleTestCase):
    @parameterized.expand(
        [
            ("within_dataset_timeout", timedelta(minutes=20), "pending", None),
            ("past_dataset_timeout", timedelta(minutes=36), "failed", STUCK_EXPORT_MESSAGE),
        ]
    )
    def test_dataset_export_timeout(
        self,
        _name: str,
        age: timedelta,
        expected_status: str,
        expected_exception: str | None,
    ) -> None:
        asset = ExportedAsset(
            export_format=JSONL_EXPORT_FORMAT,
            export_context={"kind": DATASET_EXPORT_KIND},
            created_at=now() - age,
        )

        self.assertEqual(get_export_asset_status(asset), expected_status)
        self.assertEqual(get_export_asset_effective_exception(asset), expected_exception)
