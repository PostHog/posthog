from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from django.utils import timezone

from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.endpoints.backend.models import Endpoint, EndpointVersion
from products.endpoints.backend.tasks import (
    STALE_THRESHOLD_DAYS,
    _deactivate_version_materialization,
    deactivate_stale_materializations,
)

pytestmark = [pytest.mark.django_db]


class TestDeactivateStaleMaterializationsTask(BaseTest):
    def setUp(self):
        super().setUp()
        self.sample_hogql_query = {
            "kind": "HogQLQuery",
            "query": "SELECT event FROM events LIMIT 100",
        }

    def _create_materialized_endpoint(
        self,
        name: str,
        last_run_at=None,
        last_executed_at=None,
        materialization_created_at=None,
    ) -> tuple[Endpoint, EndpointVersion]:
        """Create an endpoint with a materialized version."""
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query=self.sample_hogql_query,
            is_materialized=True,
            last_run_at=last_run_at or timezone.now(),
            sync_frequency_interval=timedelta(hours=24),
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )
        # Update saved_query.created_at if specified
        if materialization_created_at:
            DataWarehouseSavedQuery.objects.filter(id=saved_query.id).update(created_at=materialization_created_at)
            saved_query.refresh_from_db()

        endpoint = Endpoint.objects.create(
            name=name,
            team=self.team,
            created_by=self.user,
            is_active=True,
            last_executed_at=last_executed_at,
            current_version=1,
        )
        version = EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=self.sample_hogql_query,
            created_by=self.user,
            saved_query=saved_query,
            is_materialized=True,
        )
        return endpoint, version

    @mock.patch("products.data_warehouse.backend.data_load.saved_query_service.delete_saved_query_schedule")
    def test_deactivates_endpoint_not_executed_in_30_days(self, mock_delete_schedule):
        now = timezone.now()
        # Materialization enabled 45 days ago, last executed 45 days ago
        endpoint, version = self._create_materialized_endpoint(
            "stale_endpoint",
            last_run_at=now - timedelta(hours=1),
            last_executed_at=now - timedelta(days=45),
            materialization_created_at=now - timedelta(days=45),
        )

        deactivate_stale_materializations()

        version.refresh_from_db()
        assert version.saved_query is None

        saved_query = DataWarehouseSavedQuery.objects.get(name__startswith="POSTHOG_DELETED_")
        assert saved_query.deleted is True
        assert saved_query.is_materialized is False

    @mock.patch("products.data_warehouse.backend.data_load.saved_query_service.delete_saved_query_schedule")
    def test_keeps_endpoint_executed_recently(self, mock_delete_schedule):
        now = timezone.now()
        # Materialization enabled 45 days ago, but executed 5 days ago
        endpoint, version = self._create_materialized_endpoint(
            "active_endpoint",
            last_run_at=now - timedelta(hours=1),
            last_executed_at=now - timedelta(days=5),
            materialization_created_at=now - timedelta(days=45),
        )

        deactivate_stale_materializations()

        version.refresh_from_db()
        assert version.saved_query is not None
        assert version.saved_query.is_materialized is True

    @mock.patch("products.data_warehouse.backend.data_load.saved_query_service.delete_saved_query_schedule")
    def test_keeps_newly_materialized_endpoint(self, mock_delete_schedule):
        now = timezone.now()
        # Materialization enabled today, never executed
        endpoint, version = self._create_materialized_endpoint(
            "new_materialization",
            last_run_at=now - timedelta(hours=1),
            last_executed_at=None,
            materialization_created_at=now - timedelta(days=1),
        )

        deactivate_stale_materializations()

        # Should not be deactivated - materialization is too new
        version.refresh_from_db()
        assert version.saved_query is not None

    @mock.patch("products.data_warehouse.backend.data_load.saved_query_service.delete_saved_query_schedule")
    def test_keeps_endpoint_with_old_execution_but_new_materialization(self, mock_delete_schedule):
        now = timezone.now()
        # Endpoint was executed 45 days ago, but materialization enabled today
        endpoint, version = self._create_materialized_endpoint(
            "old_execution_new_materialization",
            last_run_at=now - timedelta(hours=1),
            last_executed_at=now - timedelta(days=45),
            materialization_created_at=now - timedelta(days=1),
        )

        deactivate_stale_materializations()

        # Should NOT be deactivated - materialization was just enabled
        version.refresh_from_db()
        assert version.saved_query is not None

    @mock.patch("products.data_warehouse.backend.data_load.saved_query_service.delete_saved_query_schedule")
    def test_keeps_old_materialization_that_was_never_executed(self, mock_delete_schedule):
        now = timezone.now()
        # Materialization enabled 45 days ago but never executed via API key
        endpoint, version = self._create_materialized_endpoint(
            "never_executed",
            last_run_at=now - timedelta(hours=1),
            last_executed_at=None,
            materialization_created_at=now - timedelta(days=45),
        )

        deactivate_stale_materializations()

        # Should not be deactivated - last_executed_at is null (never used via API)
        version.refresh_from_db()
        assert version.saved_query is not None

    @mock.patch("products.data_warehouse.backend.data_load.saved_query_service.delete_saved_query_schedule")
    def test_skips_endpoints_not_materialized_recently(self, mock_delete_schedule):
        now = timezone.now()
        # Materialization ran 2 days ago (not within 24h)
        endpoint, version = self._create_materialized_endpoint(
            "old_materialization_run",
            last_run_at=now - timedelta(days=2),
            last_executed_at=now - timedelta(days=45),
            materialization_created_at=now - timedelta(days=45),
        )

        deactivate_stale_materializations()

        # Should not be processed since materialization didn't run within 24h
        version.refresh_from_db()
        assert version.saved_query is not None

    @mock.patch("products.data_warehouse.backend.data_load.saved_query_service.delete_saved_query_schedule")
    def test_handles_multiple_endpoints(self, mock_delete_schedule):
        now = timezone.now()

        # Stale endpoint (materialized and last executed 45 days ago)
        stale_endpoint, stale_version = self._create_materialized_endpoint(
            "stale_endpoint",
            last_run_at=now - timedelta(hours=1),
            last_executed_at=now - timedelta(days=45),
            materialization_created_at=now - timedelta(days=45),
        )

        # Active endpoint (executed recently)
        active_endpoint, active_version = self._create_materialized_endpoint(
            "active_endpoint",
            last_run_at=now - timedelta(hours=1),
            last_executed_at=now - timedelta(days=5),
            materialization_created_at=now - timedelta(days=45),
        )

        deactivate_stale_materializations()

        stale_version.refresh_from_db()
        active_version.refresh_from_db()

        assert stale_version.saved_query is None  # Deactivated
        assert active_version.saved_query is not None  # Kept

    def test_no_endpoints_found(self):
        # No materialized endpoints exist
        with mock.patch("products.endpoints.backend.tasks.logger") as mock_logger:
            deactivate_stale_materializations()
            mock_logger.info.assert_called_with("deactivate_stale_materializations_no_candidates")

    @mock.patch("products.data_warehouse.backend.data_load.saved_query_service.delete_saved_query_schedule")
    def test_handles_endpoint_exactly_at_threshold(self, mock_delete_schedule):
        now = timezone.now()
        # Materialization enabled and last executed exactly 30 days ago
        endpoint, version = self._create_materialized_endpoint(
            "threshold_endpoint",
            last_run_at=now - timedelta(hours=1),
            last_executed_at=now - timedelta(days=STALE_THRESHOLD_DAYS),
            materialization_created_at=now - timedelta(days=STALE_THRESHOLD_DAYS),
        )

        deactivate_stale_materializations()

        # Should be deactivated because it's at or past the threshold
        version.refresh_from_db()
        assert version.saved_query is None


class TestDeactivateEndpointMaterialization(BaseTest):
    def setUp(self):
        super().setUp()
        self.sample_hogql_query = {
            "kind": "HogQLQuery",
            "query": "SELECT event FROM events LIMIT 100",
        }

    @mock.patch("products.data_warehouse.backend.data_load.saved_query_service.delete_saved_query_schedule")
    def test_deactivates_materialization_and_soft_deletes_saved_query(self, mock_delete_schedule):
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="to_deactivate",
            query=self.sample_hogql_query,
            is_materialized=True,
            last_run_at=timezone.now(),
            sync_frequency_interval=timedelta(hours=24),
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )
        endpoint = Endpoint.objects.create(
            name="to_deactivate",
            team=self.team,
            created_by=self.user,
            is_active=True,
            current_version=1,
        )
        version = EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=self.sample_hogql_query,
            created_by=self.user,
            saved_query=saved_query,
            is_materialized=True,
        )

        _deactivate_version_materialization(version)

        version.refresh_from_db()
        assert version.saved_query is None
        assert version.is_materialized is False

        saved_query.refresh_from_db()
        assert saved_query.deleted is True
        assert saved_query.is_materialized is False
        assert saved_query.sync_frequency_interval is None
        assert saved_query.last_run_at is None

    def test_handles_endpoint_without_saved_query(self):
        endpoint = Endpoint.objects.create(
            name="no_saved_query",
            team=self.team,
            created_by=self.user,
            is_active=True,
            current_version=1,
        )
        version = EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=self.sample_hogql_query,
            created_by=self.user,
        )

        # Should not raise an exception
        _deactivate_version_materialization(version)

        version.refresh_from_db()
        assert version.saved_query is None
