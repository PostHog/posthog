from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, mock_open, patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from boto3 import resource
from botocore.client import Config
from parameterized import parameterized
from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)
from prometheus_client import REGISTRY

from posthog.hogql.errors import AccessDeniedError, QueryError

from posthog.caching.fetch_from_cache import InsightResult
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.tasks import image_exporter
from products.exports.backend.tasks.failure_handler import BrowserlessUnavailable, InvalidExportContext
from products.product_analytics.backend.api.insight_variable import map_stale_to_latest
from products.product_analytics.backend.models.insight import Insight
from products.product_analytics.backend.models.insight_variable import InsightVariable


def make_insight_result(cache_key: str) -> InsightResult:
    """Helper to create InsightResult with required fields for testing."""
    return InsightResult(
        result=[],
        last_refresh=datetime.now(),
        cache_key=cache_key,
        is_cached=False,
        timezone="UTC",
    )


TEST_PREFIX = "Test-Exports"


@patch("products.exports.backend.tasks.image_exporter._screenshot_asset_browserless")
@patch(
    "products.exports.backend.tasks.image_exporter.open",
    new_callable=mock_open,
    read_data=b"image_data",
)
@patch("os.remove")
@override_settings(BROWSERLESS_CDP_URL="wss://chrome.browserless.example")
class TestImageExporter(APIBaseTest):
    exported_asset: ExportedAsset

    def setup_method(self, method: Any) -> None:
        insight = Insight.objects.create(
            team=self.team,
            query={
                "kind": "DataVisualizationNode",
                "source": {"kind": "HogQLQuery", "query": "SELECT 1 as value"},
            },
        )
        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=insight,
        )
        self.exported_asset = asset

    def teardown_method(self, method: Any) -> None:
        s3 = resource(
            "s3",
            endpoint_url=OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        bucket = s3.Bucket(OBJECT_STORAGE_BUCKET)
        bucket.objects.filter(Prefix=TEST_PREFIX).delete()

    def test_export_without_renderable_target_raises_invalid_export_context(self, *args: Any) -> None:
        exported_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context={},
        )

        with self.assertRaises(InvalidExportContext):
            image_exporter._export_to_png(exported_asset)

    def test_image_exporter_writes_to_asset_when_object_storage_is_disabled(self, *args: Any) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            image_exporter.export_image(self.exported_asset)

            assert self.exported_asset.content == b"image_data"
            assert self.exported_asset.content_location is None

    @patch("products.exports.backend.models.exported_asset.UUIDT")
    def test_image_exporter_writes_to_object_storage_when_object_storage_is_enabled(
        self, mocked_uuidt: Any, *args: Any
    ) -> None:
        mocked_uuidt.return_value = "a-guid"
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_EXPORTS_FOLDER="Test-Exports"):
            image_exporter.export_image(self.exported_asset)

            assert (
                self.exported_asset.content_location
                == f"{TEST_PREFIX}/png/team-{self.team.id}/task-{self.exported_asset.id}/a-guid"
            )

            content = object_storage.read_bytes(self.exported_asset.content_location)
            assert content == b"image_data"

            assert self.exported_asset.content is None

    @patch("products.exports.backend.models.exported_asset.UUIDT")
    @patch("products.exports.backend.models.exported_asset.object_storage.write")
    def test_image_exporter_writes_to_object_storage_when_object_storage_write_fails(
        self, mocked_object_storage_write: Any, mocked_uuidt: Any, *args: Any
    ) -> None:
        mocked_uuidt.return_value = "a-guid"
        mocked_object_storage_write.side_effect = ObjectStorageError("mock write failed")

        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_EXPORTS_FOLDER="Test-Exports"):
            image_exporter.export_image(self.exported_asset)

            assert self.exported_asset.content_location is None

            assert self.exported_asset.content == b"image_data"

    @patch("products.exports.backend.tasks.image_exporter.calculate_for_query_based_insight")
    def test_dashboard_export_calculates_all_insights(self, mock_calculate: Any, *args: Any) -> None:
        mock_calculate.return_value = make_insight_result("test_cache_key")

        dashboard = Dashboard.objects.create(team=self.team, name="Test Dashboard")
        insight_count = 3

        insights = []
        for i in range(insight_count):
            insight = Insight.objects.create(
                team=self.team,
                name=f"SQL Insight {i}",
                query={
                    "kind": "DataVisualizationNode",
                    "source": {"kind": "HogQLQuery", "query": f"SELECT {i} as value"},
                },
            )
            insights.append(insight)
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        dashboard_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            dashboard=dashboard,
            insight=None,
        )

        with self.settings(OBJECT_STORAGE_ENABLED=False):
            image_exporter.export_image(dashboard_asset)

        assert mock_calculate.call_count == insight_count, (
            f"Expected cache warming for {insight_count} insights, got {mock_calculate.call_count} calls"
        )

        for i, call in enumerate(mock_calculate.call_args_list):
            call_kwargs = call[1]

            assert call_kwargs["dashboard"].id == dashboard.id, f"Call {i + 1} missing dashboard"

            assert call_kwargs["execution_mode"] == ExecutionMode.CALCULATE_BLOCKING_ALWAYS, (
                f"Call {i + 1} should use CALCULATE_BLOCKING_ALWAYS, got {call_kwargs['execution_mode']}"
            )

            # First positional arg is the insight
            called_insight = call[0][0]
            assert called_insight.id in [ins.id for ins in insights], (
                f"Call {i + 1} has unexpected insight {called_insight.id}"
            )

    @patch("products.exports.backend.tasks.image_exporter.calculate_for_query_based_insight")
    def test_export_captures_cache_keys_and_passes_to_url(
        self,
        mock_calculate: Any,
        mock_remove: Any,
        mock_open: Any,
        mock_screenshot_asset: Any,
    ) -> None:
        """Test that cache keys from warming are captured and passed to the screenshot URL."""
        insight = Insight.objects.create(
            team=self.team,
            name="Test Insight",
            query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "SELECT 1 as value"}},
        )
        exported_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=insight,
        )

        mock_calculate.return_value = make_insight_result("test_cache_key_123")

        with self.settings(OBJECT_STORAGE_ENABLED=False):
            image_exporter.export_image(exported_asset)

        # Verify _screenshot_asset was called with a URL containing cache_keys
        assert mock_screenshot_asset.called
        call_args = mock_screenshot_asset.call_args
        url_to_render = call_args[0][1]  # Second positional arg is the URL

        assert "cache_keys=" in url_to_render, f"URL should contain cache_keys parameter: {url_to_render}"
        assert "test_cache_key_123" in url_to_render, f"URL should contain the cache key: {url_to_render}"

    @patch("products.exports.backend.tasks.image_exporter.calculate_for_query_based_insight")
    def test_dashboard_export_captures_all_cache_keys(
        self,
        mock_calculate: Any,
        mock_remove: Any,
        mock_open: Any,
        mock_screenshot_asset: Any,
    ) -> None:
        """Test that cache keys for all insights in a dashboard are captured and passed to URL."""
        dashboard = Dashboard.objects.create(team=self.team, name="Test Dashboard")

        insights = []
        for i in range(3):
            insight = Insight.objects.create(
                team=self.team,
                name=f"Insight {i}",
                query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": f"SELECT {i}"}},
            )
            insights.append(insight)
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        dashboard_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            dashboard=dashboard,
        )

        def mock_calc(insight: Any, **kwargs: Any) -> InsightResult:
            return make_insight_result(f"cache_key_for_insight_{insight.id}")

        mock_calculate.side_effect = mock_calc

        with self.settings(OBJECT_STORAGE_ENABLED=False):
            image_exporter.export_image(dashboard_asset)

        # Verify _screenshot_asset was called with URL containing all cache keys
        assert mock_screenshot_asset.called
        url_to_render = mock_screenshot_asset.call_args[0][1]

        # URL should contain cache_keys for all insights
        for insight in insights:
            assert f"cache_key_for_insight_{insight.id}" in url_to_render, (
                f"URL should contain cache key for insight {insight.id}"
            )

    @patch("products.exports.backend.tasks.image_exporter.calculate_for_query_based_insight")
    def test_dashboard_export_survives_tile_access_denied(self, mock_calculate: Any, *args: Any) -> None:
        # A tile the export owner can't read (e.g. a denied warehouse table) must degrade to its
        # access-denied render state, not crash the whole export into error tracking.
        dashboard = Dashboard.objects.create(team=self.team, name="Test Dashboard")

        accessible = Insight.objects.create(
            team=self.team,
            name="Accessible",
            query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "SELECT 1"}},
        )
        denied = Insight.objects.create(
            team=self.team,
            name="Denied warehouse table",
            query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "SELECT 2"}},
        )
        DashboardTile.objects.create(dashboard=dashboard, insight=accessible)
        DashboardTile.objects.create(dashboard=dashboard, insight=denied)

        dashboard_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            dashboard=dashboard,
        )

        def mock_calc(insight: Any, **kwargs: Any) -> InsightResult:
            if insight.id == denied.id:
                raise AccessDeniedError("You don't have access to table `customer_billing_summary`.")
            return make_insight_result(f"cache_key_for_insight_{insight.id}")

        mock_calculate.side_effect = mock_calc

        mock_screenshot_asset = args[-1]
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            image_exporter.export_image(dashboard_asset)

        # Export completed (screenshot taken) despite the denied tile.
        assert mock_screenshot_asset.called
        url_to_render = mock_screenshot_asset.call_args[0][1]
        assert f"cache_key_for_insight_{accessible.id}" in url_to_render
        assert f"cache_key_for_insight_{denied.id}" not in url_to_render

    @patch("products.exports.backend.tasks.image_exporter._screenshot_asset_browserless")
    @patch("products.exports.backend.tasks.image_exporter.open", new_callable=mock_open, read_data=b"image_data")
    @patch("os.remove")
    def test_export_includes_dashboard_variables(self, *args: Any) -> None:
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Test Dashboard with Variables",
            variables={"test_var": {"id": "var_123", "name": "test_var", "type": "String", "default": "value1"}},
        )

        InsightVariable.objects.create(team=self.team, name="test_var", type="String", default_value="value1")

        insight = Insight.objects.create(
            team=self.team,
            name="Test Insight",
            query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "SELECT 1 as value"}},
        )
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        exported_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            dashboard=dashboard,
            insight=insight,
        )

        with patch("products.exports.backend.tasks.image_exporter.calculate_for_query_based_insight") as mock_calculate:
            mock_calculate.return_value = make_insight_result("test_key")

            with self.settings(OBJECT_STORAGE_ENABLED=False):
                image_exporter.export_image(exported_asset)

            assert mock_calculate.call_count == 1
            call_kwargs = mock_calculate.call_args[1]

            assert "variables_override" in call_kwargs, "variables_override parameter missing"
            assert call_kwargs["variables_override"] is not None, (
                "variables_override should not be None when dashboard has variables"
            )

            variables = list(InsightVariable.objects.filter(team=self.team).all())
            expected_variables = map_stale_to_latest(dashboard.variables or {}, variables)
            assert call_kwargs["variables_override"] == expected_variables, (
                "variables_override should match the transformed dashboard variables"
            )

    @patch("products.exports.backend.tasks.image_exporter._screenshot_asset_browserless")
    @patch("products.exports.backend.tasks.image_exporter.open", new_callable=mock_open, read_data=b"image_data")
    @patch("os.remove")
    def test_export_includes_tile_filter_overrides(self, *args: Any) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Dashboard with Tile Filters")
        insight = Insight.objects.create(
            team=self.team,
            name="Test Insight",
            query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "SELECT 1"}},
        )
        tile_filters = {"date_from": "-7d", "properties": [{"key": "$browser", "value": "Chrome"}]}
        DashboardTile.objects.create(dashboard=dashboard, insight=insight, filters_overrides=tile_filters)

        exported_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            dashboard=dashboard,
            insight=insight,
        )

        with patch("products.exports.backend.tasks.image_exporter.calculate_for_query_based_insight") as mock_calculate:
            mock_calculate.return_value = make_insight_result("test_key")

            with self.settings(OBJECT_STORAGE_ENABLED=False):
                image_exporter.export_image(exported_asset)

            assert mock_calculate.call_count == 1
            call_kwargs = mock_calculate.call_args[1]

            assert "tile_filters_override" in call_kwargs, "tile_filters_override parameter missing"
            assert call_kwargs["tile_filters_override"] == tile_filters, (
                "tile_filters_override should match tile filters"
            )

    @parameterized.expand(
        [
            (
                "with_source_override",
                {"source": {"kind": "HogQLQuery", "query": "SELECT 1"}},
                {"kind": "HogQLQuery", "query": "SELECT 1"},
                False,
            ),
            (
                "with_source_and_dashboard_variables",
                {"source": {"kind": "HogQLQuery", "query": "SELECT 1"}},
                {"kind": "HogQLQuery", "query": "SELECT 1"},
                True,
            ),
            (
                "source_vars_not_overridden_by_dashboard_vars",
                {
                    "source": {
                        "kind": "HogQLQuery",
                        "query": "SELECT 1",
                        "variables": {"var_1": {"code_name": "eventName", "value": "$pageview"}},
                    }
                },
                {
                    "kind": "HogQLQuery",
                    "query": "SELECT 1",
                    "variables": {"var_1": {"code_name": "eventName", "value": "$pageview"}},
                },
                True,
            ),
            (
                "without_export_context",
                None,
                None,
                False,
            ),
        ]
    )
    @patch("products.exports.backend.tasks.image_exporter.calculate_for_query_based_insight")
    def test_insight_export_query_override_routing(
        self,
        _name: str,
        export_context: dict | None,
        expected_query_override: dict | None,
        with_dashboard: bool,
        mock_calculate: Any,
        *args: Any,
    ) -> None:
        dashboard = None
        variable = None
        if with_dashboard:
            dashboard = Dashboard.objects.create(
                team=self.team,
                name="Dashboard",
                variables={"var_1": {"code_name": "eventName", "value": "dashboard_value"}},
            )
            variable = InsightVariable.objects.create(
                team=self.team, name="eventName", code_name="eventName", type="String"
            )

        insight = Insight.objects.create(
            team=self.team,
            name="SQL Insight",
            query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "SELECT 1"}},
        )
        if dashboard:
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        exported_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=insight,
            dashboard=dashboard,
            export_context=export_context,
        )

        mock_calculate.return_value = make_insight_result("test_key")
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            image_exporter.export_image(exported_asset)

        call_kwargs = mock_calculate.call_args[1]
        if expected_query_override is not None:
            assert call_kwargs["query_override"] == expected_query_override
        else:
            assert "query_override" not in call_kwargs

        if expected_query_override is not None:
            # When query_override is present, variables_override must be None —
            # the user's current state is already embedded in query_override
            assert call_kwargs["variables_override"] is None
        elif variable:
            variable_id = str(variable.id)
            assert call_kwargs["variables_override"] == {
                variable_id: {
                    "code_name": "eventName",
                    "value": "dashboard_value",
                    "variableId": variable_id,
                }
            }
        else:
            assert call_kwargs["variables_override"] is None

    @parameterized.expand(
        [
            (
                "uses_export_context_override",
                {
                    "variables_override": {
                        "var_1": {"variableId": "var_1", "code_name": "eventName", "value": "$pageview"}
                    }
                },
                True,
            ),
            (
                "falls_back_to_saved_variables",
                None,
                False,
            ),
        ]
    )
    @patch("products.exports.backend.tasks.image_exporter.calculate_for_query_based_insight")
    def test_dashboard_export_variables_routing(
        self,
        _name: str,
        export_context: dict | None,
        uses_context_directly: bool,
        mock_calculate: Any,
        *args: Any,
    ) -> None:
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Dashboard",
            variables={"var_1": {"code_name": "eventName", "value": "saved_value"}},
        )
        variable = InsightVariable.objects.create(
            team=self.team, name="eventName", code_name="eventName", type="String"
        )
        insight = Insight.objects.create(
            team=self.team,
            name="SQL Insight",
            query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "SELECT 1"}},
        )
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        dashboard_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            dashboard=dashboard,
            export_context=export_context,
        )

        mock_calculate.return_value = make_insight_result("test_key")
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            image_exporter.export_image(dashboard_asset)

        call_kwargs = mock_calculate.call_args[1]
        if uses_context_directly:
            assert call_kwargs["variables_override"] == export_context["variables_override"]  # type: ignore[index]
        else:
            variable_id = str(variable.id)
            assert call_kwargs["variables_override"] == {
                variable_id: {
                    "code_name": "eventName",
                    "value": "saved_value",
                    "variableId": variable_id,
                }
            }


@patch("products.exports.backend.tasks.image_exporter._screenshot_asset_browserless")
@patch("products.exports.backend.tasks.image_exporter.open", new_callable=mock_open, read_data=b"image_data")
@patch("os.remove")
@override_settings(BROWSERLESS_CDP_URL="wss://chrome.browserless.example")
class TestHeatmapExportURLEncoding(APIBaseTest):
    def test_heatmap_urls_with_query_params_are_encoded_in_exporter_url(
        self,
        mock_remove: Any,
        mock_open: Any,
        mock_screenshot_asset: Any,
    ) -> None:
        data_url = "/api/environments/1/heatmap_screenshots/abc/content/?width=1024&format=jpeg"
        exported_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context={
                "heatmap_url": "https://example.com/page?tab=home",
                "heatmap_data_url": data_url,
            },
        )

        with self.settings(OBJECT_STORAGE_ENABLED=False):
            image_exporter.export_image(exported_asset)

        url_to_render = mock_screenshot_asset.call_args[0][1]

        # Verify URL parsing recovers the full values (same as browser URL parsing)

        parsed = urlparse(url_to_render)
        params = parse_qs(parsed.query)

        assert params["pageURL"] == ["https://example.com/page?tab=home"]
        assert params["dataURL"] == [data_url]
        assert set(params.keys()) == {"token", "pageURL", "dataURL"}

    def test_without_encoding_inner_ampersands_corrupt_query_string(
        self,
        mock_remove: Any,
        mock_open: Any,
        mock_screenshot_asset: Any,
    ) -> None:
        # Data URLs with multiple query params (e.g. `?width=1024&format=jpeg`)
        # contain `&` which, without encoding, splits into separate top-level params
        # and truncates the dataURL value the exporter receives.

        data_url = "/api/environments/1/heatmap_screenshots/abc/content/?width=1024&format=jpeg"
        unencoded = f"https://example.com/exporter?token=fake&pageURL=https://example.com&dataURL={data_url}"

        parsed = urlparse(unencoded)
        params = parse_qs(parsed.query)

        # The inner `&format=jpeg` leaks as a top-level param
        assert "format" in params, "Inner &format leaked as top-level param"
        # And the dataURL is truncated — missing `&format=jpeg`
        assert params["dataURL"] == ["/api/environments/1/heatmap_screenshots/abc/content/?width=1024"]
        assert params["dataURL"] != [data_url]


@patch("products.exports.backend.tasks.image_exporter._screenshot_asset_browserless")
@patch("products.exports.backend.tasks.image_exporter.open", new_callable=mock_open, read_data=b"image_data")
@patch("os.remove")
@override_settings(BROWSERLESS_CDP_URL="wss://chrome.browserless.example")
class TestImageExporterQueryOverrideE2E(ClickhouseTestMixin, APIBaseTest):
    def test_query_override_produces_different_results_than_saved_query(
        self,
        mock_remove: Any,
        mock_open: Any,
        mock_screenshot_asset: Any,
    ) -> None:
        _create_event(distinct_id="user1", event="$pageview", team=self.team)
        _create_event(distinct_id="user1", event="$pageview", team=self.team)
        _create_event(distinct_id="user1", event="$pageleave", team=self.team)
        flush_persons_and_events()

        variable = InsightVariable.objects.create(
            team=self.team, name="eventName", code_name="eventName", type="String", default_value="$pageleave"
        )
        variable_id = str(variable.id)

        query_source = {
            "kind": "HogQLQuery",
            "query": "SELECT event, count() AS total FROM events WHERE event = {variables.eventName} GROUP BY event",
            "variables": {
                variable_id: {"variableId": variable_id, "code_name": "eventName", "value": "$pageleave"},
            },
        }
        insight = Insight.objects.create(
            team=self.team,
            name="SQL Insight",
            query={"kind": "DataVisualizationNode", "source": query_source},
        )

        # Export with saved defaults ($pageleave)
        asset_default = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=insight,
        )
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            image_exporter.export_image(asset_default)

        # Export with user override ($pageview) via export_context
        override_source = {
            **query_source,
            "variables": {
                variable_id: {"variableId": variable_id, "code_name": "eventName", "value": "$pageview"},
            },
        }
        asset_override = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=insight,
            export_context={"source": override_source},
        )
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            image_exporter.export_image(asset_override)

        assert asset_default.content is not None
        assert asset_override.content is not None

        # Different variables should produce different screenshot URLs (different cache keys)
        screenshot_calls = mock_screenshot_asset.call_args_list
        url_default = screenshot_calls[0][0][1]
        url_override = screenshot_calls[1][0][1]

        assert "cache_keys=" in url_default
        assert "cache_keys=" in url_override
        assert url_default != url_override


class TestBuildCdpEndpoint(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain_wss", "wss://chrome.browserless.io", "tok123", 180000, "wss", "chrome.browserless.io", "tok123"),
            (
                "existing_query_param",
                "wss://chrome.browserless.io?launch=stealth",
                "tok123",
                90000,
                "wss",
                "chrome.browserless.io",
                "tok123",
            ),
            ("empty_token", "wss://chrome.browserless.io", "", 60000, "wss", "chrome.browserless.io", None),
            ("wss_scheme_preserved", "wss://example.org/cdp", "abc", 120000, "wss", "example.org", "abc"),
        ]
    )
    def test_build_cdp_endpoint(
        self,
        _name: str,
        cdp_url: str,
        token: str,
        session_timeout_ms: int,
        expected_scheme: str,
        expected_host: str,
        expected_token: str | None,
    ) -> None:
        result = image_exporter._build_cdp_endpoint(cdp_url, token, session_timeout_ms)

        parsed = urlparse(result)
        params = parse_qs(parsed.query)

        assert parsed.scheme == expected_scheme
        assert parsed.netloc == expected_host
        assert params["timeout"] == [str(session_timeout_ms)]

        if expected_token is None:
            assert "token" not in params
        else:
            assert params["token"] == [expected_token]

    def test_build_cdp_endpoint_preserves_path_and_existing_param(self) -> None:
        result = image_exporter._build_cdp_endpoint("wss://example.org/cdp?launch=stealth", "tok", 1000)

        parsed = urlparse(result)
        params = parse_qs(parsed.query)

        assert parsed.path == "/cdp"
        assert params["launch"] == ["stealth"]
        assert params["token"] == ["tok"]
        assert params["timeout"] == ["1000"]


class TestScreenshotAssetBrowserless(SimpleTestCase):
    def test_connect_error_is_wrapped_as_browserless_unavailable(self) -> None:
        playwright_obj = MagicMock()
        playwright_obj.chromium.connect_over_cdp.side_effect = PlaywrightError("ECONNREFUSED")

        # Mock the `with sync_playwright() as p:` shape: the context manager's
        # __enter__ returns the playwright object whose .chromium.connect_over_cdp raises.
        sync_playwright_cm = MagicMock()
        sync_playwright_cm.__enter__.return_value = playwright_obj

        with patch(
            "products.exports.backend.tasks.image_exporter.sync_playwright",
            return_value=sync_playwright_cm,
        ):
            with patch.object(settings, "BROWSERLESS_CDP_URL", "wss://chrome.browserless.io"):
                with self.assertRaises(BrowserlessUnavailable):
                    image_exporter._screenshot_asset_browserless("p", "u", 800, ".ExportedInsight")

    def test_connect_error_redacts_token_and_breaks_chain(self) -> None:
        token = "super-secret-token"
        leaked = (
            f"connect_over_cdp: WebSocket error connecting to wss://chrome.browserless.io/?token={token}&timeout=180000"
        )
        playwright_obj = MagicMock()
        playwright_obj.chromium.connect_over_cdp.side_effect = PlaywrightError(leaked)
        sync_playwright_cm = MagicMock()
        sync_playwright_cm.__enter__.return_value = playwright_obj

        with (
            patch("products.exports.backend.tasks.image_exporter.sync_playwright", return_value=sync_playwright_cm),
            patch.object(settings, "BROWSERLESS_CDP_URL", "wss://chrome.browserless.io"),
            patch.object(settings, "BROWSERLESS_TOKEN", token),
        ):
            with self.assertRaises(BrowserlessUnavailable) as ctx:
                image_exporter._screenshot_asset_browserless("p", "u", 800, ".ExportedInsight")

        message = str(ctx.exception)
        assert token not in message
        assert "***" in message
        assert ctx.exception.__cause__ is None
        assert ctx.exception.__suppress_context__ is True

    def test_goto_timeout_is_captured_and_reraised(self) -> None:
        # Connect succeeds, but navigation times out — the debug-capture path must run
        # for a goto (navigation) timeout, not just a selector timeout.
        page = MagicMock()
        page.goto.side_effect = PlaywrightTimeoutError("Timeout 30000ms exceeded")
        context = MagicMock()
        context.new_page.return_value = page
        browser = MagicMock()
        browser.new_context.return_value = context
        playwright_obj = MagicMock()
        playwright_obj.chromium.connect_over_cdp.return_value = browser
        sync_playwright_cm = MagicMock()
        sync_playwright_cm.__enter__.return_value = playwright_obj

        with (
            patch(
                "products.exports.backend.tasks.image_exporter.sync_playwright",
                return_value=sync_playwright_cm,
            ),
            patch.object(settings, "BROWSERLESS_CDP_URL", "wss://chrome.browserless.io"),
            patch("products.exports.backend.tasks.image_exporter.capture_exception") as mock_capture,
        ):
            with self.assertRaises(PlaywrightTimeoutError) as ctx:
                image_exporter._screenshot_asset_browserless("p", "u", 800, ".ExportedInsight")

        mock_capture.assert_called_once()
        # The re-raise preserves the original timeout as its cause (the message carries no secret, so chaining is safe).
        assert isinstance(ctx.exception.__cause__, PlaywrightTimeoutError)
        assert "Timeout 30000ms exceeded" in str(ctx.exception.__cause__)


class TestDimensionHelpers(SimpleTestCase):
    @parameterized.expand(
        [
            ("int_within_bounds", 1200, 800, 1200),
            ("float_truncated", 1200.9, 800, 1200),
            ("none_falls_back", None, 800, 800),
            ("zero_falls_back", 0, 800, 800),
            ("non_numeric_str_falls_back", "not-a-number", 800, 800),
            ("above_max_capped", image_exporter.MAX_WIDTH_PIXELS + 1000, 800, image_exporter.MAX_WIDTH_PIXELS),
        ]
    )
    def test_resolve_width(self, _name: str, raw_width: Any, screenshot_width: int, expected: int) -> None:
        assert image_exporter._resolve_width(raw_width, screenshot_width, "https://example.com") == expected

    @parameterized.expand(
        [
            ("none_uses_max", None, image_exporter.MAX_HEIGHT_PIXELS),
            ("zero_uses_max", 0, image_exporter.MAX_HEIGHT_PIXELS),
            ("below_max_uses_value", image_exporter.MAX_HEIGHT_PIXELS - 1000, image_exporter.MAX_HEIGHT_PIXELS - 1000),
            ("above_max_uses_max", image_exporter.MAX_HEIGHT_PIXELS + 1000, image_exporter.MAX_HEIGHT_PIXELS),
        ]
    )
    def test_effective_max_height(self, _name: str, max_height_pixels: Any, expected: int) -> None:
        assert image_exporter._effective_max_height(max_height_pixels) == expected

    @parameterized.expand(
        [
            ("at_or_below_max_unchanged", 3000, 5000, False, 3000),
            ("above_max_capped", 6000, 5000, False, 5000),
            ("final_above_max_capped", 6000, 5000, True, 5000),
        ]
    )
    def test_cap_height(self, _name: str, raw_height: int, effective_max: int, final: bool, expected: int) -> None:
        assert image_exporter._cap_height(raw_height, effective_max, "https://example.com", final=final) == expected


class TestMeasureContentWidthJS(SimpleTestCase):
    # The vertical funnel (FunnelStepsBarChart, quill-charts) renders neither a <table> nor a
    # .FunnelBarVertical, so the measurement JS must target its own selector. If that selector is
    # absent — or is checked after the generic <table> fallback — funnel measurement returns null,
    # _resolve_width keeps the wide 4000px funnel viewport, and the bars end up stranded on the left
    # of a mostly-empty image. The selector must stay in sync with the data-attr rendered by
    # FunnelStepsBarChart.tsx.
    def test_funnel_canvas_selector_is_present_and_measured_before_table_fallback(self) -> None:
        js = image_exporter.MEASURE_CONTENT_WIDTH_JS

        canvas_index = js.find("funnel-steps-bar-chart-canvas")
        table_fallback_index = js.find("tableElement")

        assert canvas_index != -1, "vertical funnels would fall through to the table path and never get cropped"
        assert table_fallback_index != -1
        assert canvas_index < table_fallback_index


class TestIsBrowserlessConnectionError(SimpleTestCase):
    @parameterized.expand(
        [
            ("target_closed", "Target closed", True),
            ("has_been_closed", "Browser has been closed", True),
            ("connection_closed", "Connection closed while reading", True),
            ("websocket", "WebSocket error: connection lost", True),
            ("disconnected", "Browser disconnected unexpectedly", True),
            ("econnrefused", "connect ECONNREFUSED 1.2.3.4:443", True),
            ("http_503", "Server returned 503 Service Unavailable", False),
            ("http_429", "Rejected with 429", False),
            ("too_many_requests", "Too Many Requests", False),
            (
                "render_error_url_with_timestamp",
                "page.goto: net::ERR_ABORTED at https://app.posthog.com/exporter?t=1700000000503",
                False,
            ),
            ("render_bug", "TypeError: cannot read property of undefined", False),
            ("selector_missing", "No node found for selector .ExportedInsight", False),
            ("empty", "", False),
        ]
    )
    def test_is_browserless_connection_error(self, _name: str, message: str, expected: bool) -> None:
        assert image_exporter._is_browserless_connection_error(Exception(message)) is expected


@override_settings(BROWSERLESS_CDP_URL="wss://chrome.browserless.example")
class TestImageExportRenderMetrics(APIBaseTest):
    exported_asset: ExportedAsset

    def setup_method(self, method: Any) -> None:
        insight = Insight.objects.create(
            team=self.team,
            query={
                "kind": "DataVisualizationNode",
                "source": {"kind": "HogQLQuery", "query": "SELECT 1 as value"},
            },
        )
        self.exported_asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            insight=insight,
        )

    @staticmethod
    def _sample(name: str, labels: dict[str, str]) -> float:
        # REGISTRY is global; treat a not-yet-emitted series (None) as 0 so assertions are deltas.
        return REGISTRY.get_sample_value(name, labels) or 0.0

    @patch("products.exports.backend.tasks.image_exporter.open", new_callable=mock_open, read_data=b"image_data")
    @patch("os.remove")
    @patch("products.exports.backend.tasks.image_exporter._screenshot_asset_browserless")
    def test_render_duration_success_counter_increments(self, mock_screenshot_asset: Any, *args: Any) -> None:
        success_labels = {"backend": "browserless", "outcome": "success"}
        before = self._sample("image_export_render_duration_seconds_count", success_labels)

        with self.settings(OBJECT_STORAGE_ENABLED=False):
            image_exporter.export_image(self.exported_asset)

        after = self._sample("image_export_render_duration_seconds_count", success_labels)
        assert after - before == 1
        assert mock_screenshot_asset.called

    @patch("products.exports.backend.tasks.image_exporter.open", new_callable=mock_open, read_data=b"image_data")
    @patch("os.remove")
    @patch("products.exports.backend.tasks.image_exporter._screenshot_asset_browserless")
    def test_render_failure_counters_increment(self, mock_screenshot_asset: Any, *args: Any) -> None:
        # QueryError classifies as "user" via classify_failure_type.
        mock_screenshot_asset.side_effect = QueryError("bad query")

        failure_labels = {"backend": "browserless", "failure_type": "user"}
        duration_labels = {"backend": "browserless", "outcome": "failure"}
        failure_before = self._sample("image_export_render_failure_total", failure_labels)
        duration_before = self._sample("image_export_render_duration_seconds_count", duration_labels)

        with self.settings(OBJECT_STORAGE_ENABLED=False):
            with self.assertRaises(QueryError):
                image_exporter.export_image(self.exported_asset)

        failure_after = self._sample("image_export_render_failure_total", failure_labels)
        duration_after = self._sample("image_export_render_duration_seconds_count", duration_labels)
        assert failure_after - failure_before == 1
        assert duration_after - duration_before == 1
