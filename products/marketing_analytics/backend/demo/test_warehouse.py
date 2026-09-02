import pytest
from posthog.test.base import BaseTest

from products.marketing_analytics.backend.demo import warehouse
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource


class TestAssertSeedable(BaseTest):
    def _table(self, name: str, source_id: str | None) -> DataWarehouseTable:
        source = (
            ExternalDataSource.objects.create(team=self.team, source_type="GoogleAds", source_id=source_id)
            if source_id is not None
            else None
        )
        return DataWarehouseTable.objects.create(
            team=self.team, name=name, columns={"campaign_id": "String"}, external_data_source=source
        )

    def test_a_clean_team_is_seedable(self):
        warehouse.assert_seedable(self.team)

    def test_a_previously_seeded_team_is_seedable_again(self):
        self._table("googleads_campaign", "marketing-demo-googleads")

        warehouse.assert_seedable(self.team)

    def test_a_real_integration_is_refused_and_named(self):
        self._table("googleads_campaign", "real-oauth-connection")

        with pytest.raises(ValueError) as error:
            warehouse.assert_seedable(self.team)

        assert "googleads_campaign" in str(error.value)

    def test_a_table_the_seeder_never_writes_is_ignored(self):
        self._table("some_customer_table", "real-oauth-connection")

        warehouse.assert_seedable(self.team)

    def test_a_deleted_table_does_not_block(self):
        table = self._table("googleads_campaign", "real-oauth-connection")
        table.deleted = True
        table.save()

        warehouse.assert_seedable(self.team)
