import uuid

import pytest
from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.revenue_analytics.backend.joins import get_customer_revenue_view_name

pytestmark = [pytest.mark.django_db]


class TestRevenueAnalyticsPersonJoinsAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/environments/{self.team.pk}/revenue_analytics/joins/"

    def _create_stripe_source(self, prefix="") -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type=ExternalDataSourceType.STRIPE,
            prefix=prefix,
            job_inputs={},
        )

    def _get_active_joins(self):
        return DataWarehouseJoin.objects.filter(team=self.team).exclude(deleted=True)

    def test_enable_creates_joins_for_stripe_sources(self):
        source = self._create_stripe_source(prefix="test_")

        response = self.client.post(self.url, data={"enabled": True})

        assert response.status_code == status.HTTP_200_OK
        view_name = get_customer_revenue_view_name(source.prefix)
        assert (
            self._get_active_joins()
            .filter(
                source_table_name=view_name,
                source_table_key="JSONExtractString(metadata, 'posthog_person_distinct_id')",
                joining_table_name="persons",
                joining_table_key="pdi.distinct_id",
                field_name="persons",
            )
            .exists()
        )

    def test_disable_removes_joins(self):
        source = self._create_stripe_source(prefix="test_")

        self.client.post(self.url, data={"enabled": True})

        view_name = get_customer_revenue_view_name(source.prefix)
        assert self._get_active_joins().filter(source_table_name=view_name).exists()

        response = self.client.post(self.url, data={"enabled": False})

        assert response.status_code == status.HTTP_200_OK
        assert not self._get_active_joins().filter(source_table_name=view_name).exists()

    @parameterized.expand([True, False])
    def test_cannot_change_joins_for_another_team(self, enabled: bool):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Project")
        other_url = f"/api/environments/{other_team.pk}/revenue_analytics/joins/"

        response = self.client.post(other_url, data={"enabled": enabled})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json() == self.permission_denied_response("You don't have access to the project.")

    def test_skips_disabled_sources(self):
        source = self._create_stripe_source(prefix="test_")
        source.revenue_analytics_config_safe.enabled = False
        source.revenue_analytics_config_safe.save()

        self.client.post(self.url, data={"enabled": True})

        view_name = get_customer_revenue_view_name(source.prefix)
        assert not self._get_active_joins().filter(source_table_name=view_name).exists()
