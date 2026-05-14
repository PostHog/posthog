import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from products.data_warehouse.backend.models.join import DataWarehouseJoin
from products.revenue_analytics.backend.joins import (
    ensure_person_join,
    get_customer_revenue_view_name,
    remove_person_join,
)

pytestmark = [pytest.mark.django_db]


class TestGetCustomerRevenueViewName(BaseTest):
    @parameterized.expand(
        [
            ("", "stripe.customer_revenue_view"),
            ("my_prefix_", "stripe.my_prefix.customer_revenue_view"),
            ("org_123_", "stripe.org_123.customer_revenue_view"),
        ]
    )
    def test_get_customer_revenue_view_name(self, table_prefix, expected):
        assert get_customer_revenue_view_name(table_prefix) == expected


class TestEnsurePersonJoin(BaseTest):
    def _get_active_joins(self):
        return DataWarehouseJoin.objects.filter(team=self.team).exclude(deleted=True)

    @parameterized.expand(["", None])
    def test_creates_join(self, prefix):
        ensure_person_join(self.team.pk, prefix)

        joins = self._get_active_joins()
        assert joins.count() == 1

        join = joins.first()
        assert join.source_table_name == "stripe.customer_revenue_view"
        assert join.source_table_key == "JSONExtractString(metadata, 'posthog_person_distinct_id')"
        assert join.joining_table_name == "persons"
        assert join.joining_table_key == "pdi.distinct_id"
        assert join.field_name == "persons"

    @parameterized.expand(["my_prefix_", "org_123_"])
    def test_applies_table_prefix(self, prefix):
        ensure_person_join(self.team.pk, prefix)

        join = self._get_active_joins().first()
        assert join.source_table_name == get_customer_revenue_view_name(prefix)

    def test_idempotent(self):
        ensure_person_join(self.team.pk, "")
        ensure_person_join(self.team.pk, "")

        assert self._get_active_joins().count() == 1

    def test_recreates_after_soft_delete(self):
        ensure_person_join(self.team.pk, "")
        self._get_active_joins().first().soft_delete()

        ensure_person_join(self.team.pk, "")

        assert self._get_active_joins().count() == 1
        assert DataWarehouseJoin.objects.filter(
            team=self.team, source_table_name="stripe.customer_revenue_view", deleted=True
        ).exists()


class TestRemovePersonJoin(BaseTest):
    def _get_active_joins(self):
        return DataWarehouseJoin.objects.filter(team=self.team).exclude(deleted=True)

    @parameterized.expand(["", None])
    def test_soft_deletes_join(self, prefix):
        ensure_person_join(self.team.pk, prefix)
        assert self._get_active_joins().count() == 1

        remove_person_join(self.team.pk, prefix)

        assert self._get_active_joins().count() == 0
        assert DataWarehouseJoin.objects.filter(
            team=self.team, source_table_name="stripe.customer_revenue_view", deleted=True
        ).exists()

    def test_noop_when_missing(self):
        remove_person_join(self.team.pk, "")

        assert self._get_active_joins().count() == 0

    def test_only_deletes_matching_prefix(self):
        ensure_person_join(self.team.pk, "")
        ensure_person_join(self.team.pk, "org_123_")

        remove_person_join(self.team.pk, "")

        assert self._get_active_joins().count() == 1
        assert self._get_active_joins().first().source_table_name == "stripe.org_123.customer_revenue_view"
