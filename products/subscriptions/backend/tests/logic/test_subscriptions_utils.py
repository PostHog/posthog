import pytest
import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.sharing_configuration import SharingConfiguration

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.exports.backend.models.exported_asset import ExportedAsset
from products.product_analytics.backend.facade.models import Insight
from products.subscriptions.backend.facade.contracts import SharedInsightImage
from products.subscriptions.backend.logic.subscription_utils import (
    ASSET_GENERATION_FAILED_MESSAGE,
    DEBUG_PLACEHOLDER_IMAGE_URL,
    MAX_INSIGHTS,
    generate_assets,
    shared_insight_image,
    subscription_asset_error_message,
)
from products.subscriptions.backend.tests.subscriptions_test_factory import create_subscription


@patch("products.subscriptions.backend.logic.subscription_utils.chain")
@patch("products.subscriptions.backend.logic.subscription_utils.exporter.export_asset")
class TestSubscriptionsTasksUtils(APIBaseTest):
    dashboard: Dashboard
    insight: Insight
    asset: ExportedAsset
    tiles: list[DashboardTile]

    def setUp(self) -> None:
        self.dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        self.insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")
        self.tiles = []
        for i in range(MAX_INSIGHTS + 2):
            insight = Insight.objects.create(team=self.team, short_id=f"insight-{i}", name="My Test subscription")
            self.tiles.append(DashboardTile.objects.create(dashboard=self.dashboard, insight=insight))

        self.subscription = create_subscription(team=self.team, insight=self.insight, created_by=self.user)

    def test_generate_assets_for_insight(self, mock_export_task: MagicMock, _mock_group: MagicMock) -> None:
        with self.settings(PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES=1):
            insights, assets = generate_assets(self.subscription)

            assert insights == [self.insight]
            assert len(assets) == 1
            assert mock_export_task.si.call_count == 1

    def test_generate_assets_for_dashboard(self, mock_export_task: MagicMock, _mock_group: MagicMock) -> None:
        subscription = create_subscription(team=self.team, dashboard=self.dashboard, created_by=self.user)

        with self.settings(PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES=1):
            insights, assets = generate_assets(subscription)

        assert len(insights) == len(self.tiles)
        assert len(assets) == MAX_INSIGHTS
        assert mock_export_task.si.call_count == MAX_INSIGHTS

    def test_raises_if_missing_resource(self, _mock_export_task: MagicMock, _mock_group: MagicMock) -> None:
        subscription = create_subscription(team=self.team, created_by=self.user)

        with self.settings(PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES=1), pytest.raises(Exception) as e:
            generate_assets(subscription)

        assert str(e.value) == "There are no insights to be sent for this Subscription"

    def test_excludes_deleted_insights_for_dashboard(self, mock_export_task: MagicMock, _mock_group: MagicMock) -> None:
        for i in range(1, len(self.tiles)):
            current_tile = self.tiles[i]
            if current_tile.insight is None:
                continue
            current_tile.insight.deleted = True
            current_tile.insight.save()
        subscription = create_subscription(team=self.team, dashboard=self.dashboard, created_by=self.user)

        with self.settings(PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES=1):
            insights, assets = generate_assets(subscription)

            assert len(insights) == 1
            assert len(assets) == 1
            assert mock_export_task.si.call_count == 1

    def test_cancels_children_if_timed_out(self, _mock_export_task: MagicMock, mock_group: MagicMock) -> None:
        # mock the group so that its children are never ready,
        # and we capture calls to revoke
        mock_running_exports = MagicMock()
        mock_ready = MagicMock()
        running_export_task = MagicMock()

        running_export_task.state = "PENDING"

        mock_ready.return_value = False
        mock_group.return_value.apply_async.return_value = mock_running_exports

        mock_running_exports.children = [running_export_task]
        mock_running_exports.ready = mock_ready

        with self.settings(PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES=0.01), pytest.raises(Exception) as e:
            generate_assets(self.subscription)

        assert str(e.value) == "Timed out waiting for celery task to finish"
        running_export_task.revoke.assert_called()

    @parameterized.expand([("local", True), ("deployed", False)])
    @time_machine.travel("2026-01-01T12:00:00Z", tick=False)
    def test_shared_insight_image_describes_the_shared_insight(
        self, _name: str, debug: bool, _mock_export_task: MagicMock, _mock_group: MagicMock
    ) -> None:
        insight = Insight.objects.create(team=self.team, short_id="derived", derived_name="Pageviews by browser")
        sharing_configuration = SharingConfiguration.objects.create(team=self.team, insight=insight, enabled=True)

        with self.settings(PARALLEL_ASSET_GENERATION_MAX_TIMEOUT_MINUTES=1, DEBUG=debug):
            image = shared_insight_image(sharing_configuration)
            asset_url = ExportedAsset.objects.get(insight=insight).get_public_content_url()

        assert image == SharedInsightImage(
            title="Pageviews by browser",
            image_url=DEBUG_PLACEHOLDER_IMAGE_URL if debug else asset_url,
            alt_text="Pageviews by browser",
        )


class TestSubscriptionAssetErrorMessage(APIBaseTest):
    def _asset(self, exception: str | None, exception_type: str | None = None) -> ExportedAsset:
        return ExportedAsset.objects.create(
            team=self.team,
            insight_id=self.insight.id,
            export_format="image/png",
            exception=exception,
            exception_type=exception_type,
        )

    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")

    @parameterized.expand(
        [
            (
                "passes_through_non_oom_text",
                "Unknown table 'nonexistent_table'",
                None,
                "Unknown table 'nonexistent_table'",
            ),
            (
                "replaces_out_of_memory_text",
                "This query ran out of memory before it could finish, usually because it's scanning too much data.",
                None,
                ASSET_GENERATION_FAILED_MESSAGE,
            ),
            (
                "replaces_out_of_memory_regardless_of_casing",
                "Query Ran Out Of Memory",
                None,
                ASSET_GENERATION_FAILED_MESSAGE,
            ),
            (
                "replaces_memory_limit_exception_by_type",
                "Memory limit (for query) exceeded",
                "ClickHouseQueryMemoryLimitExceeded",
                ASSET_GENERATION_FAILED_MESSAGE,
            ),
            ("falls_back_when_no_exception", None, None, ASSET_GENERATION_FAILED_MESSAGE),
        ]
    )
    def test_subscription_asset_error_message(
        self, _name: str, exception: str | None, exception_type: str | None, expected: str
    ) -> None:
        asset = self._asset(exception, exception_type)
        assert subscription_asset_error_message(asset) == expected
