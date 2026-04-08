from freezegun import freeze_time
from posthog.test.base import _create_person

from posthog.schema import CurrencyCode

from posthog.hogql.database.schema.test.base import RevenueAnalyticsTestBase
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from products.data_warehouse.backend.data_load.source_templates import _revenue_view_name, database_operations


class TestCustomerRevenueViewPersonsJoin(RevenueAnalyticsTestBase):
    """Verify that the joins created by database_operations actually resolve
    when revenue analytics queries through them."""

    def setUp(self):
        super().setUp()
        self.create_sources()
        self.team.base_currency = CurrencyCode.GBP.value
        self.team.save()
        self.view_name = _revenue_view_name(self.source.prefix or "")

    def test_persons_join_resolves_on_customer_view(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person_cus_1"],
            properties={"marker": "found"},
        )

        database_operations(self.team.pk, self.source.prefix or "")

        with freeze_time(self.QUERY_TIMESTAMP):
            response = execute_hogql_query(
                parse_select(
                    f"SELECT id, persons.properties.marker FROM {self.view_name}"
                    f" WHERE persons.properties.marker IS NOT NULL ORDER BY id"
                ),
                self.team,
                modifiers=self.MODIFIERS,
            )
        assert len(response.results) == 1
        assert response.results[0][0] == "cus_1"
        assert response.results[0][1] == "found"
