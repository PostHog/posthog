from abc import ABC
from typing import ClassVar, Optional

from posthog.schema import DatabaseSchemaManagedViewTableKind

from posthog.hogql.database.models import SavedQuery


class RevenueAnalyticsBaseView(SavedQuery, ABC):
    prefix: str
    source_id: Optional[str] = None
    event_name: Optional[str] = None

    DATABASE_SCHEMA_TABLE_KIND: ClassVar[DatabaseSchemaManagedViewTableKind]

    def is_event_view(self) -> bool:
        return self.event_name is not None

    @classmethod
    def get_generic_view_alias(cls) -> str:
        return cls.DATABASE_SCHEMA_TABLE_KIND.value


class RevenueAnalyticsChargeView(RevenueAnalyticsBaseView):
    DATABASE_SCHEMA_TABLE_KIND = DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CHARGE


class RevenueAnalyticsCustomerView(RevenueAnalyticsBaseView):
    DATABASE_SCHEMA_TABLE_KIND = DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER


class RevenueAnalyticsProductView(RevenueAnalyticsBaseView):
    DATABASE_SCHEMA_TABLE_KIND = DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_PRODUCT


class RevenueAnalyticsRevenueItemView(RevenueAnalyticsBaseView):
    DATABASE_SCHEMA_TABLE_KIND = DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM


class RevenueAnalyticsSubscriptionView(RevenueAnalyticsBaseView):
    DATABASE_SCHEMA_TABLE_KIND = DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_SUBSCRIPTION


KIND_TO_CLASS: dict[DatabaseSchemaManagedViewTableKind, type[RevenueAnalyticsBaseView]] = {
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_SUBSCRIPTION: RevenueAnalyticsSubscriptionView,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM: RevenueAnalyticsRevenueItemView,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CHARGE: RevenueAnalyticsChargeView,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER: RevenueAnalyticsCustomerView,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_PRODUCT: RevenueAnalyticsProductView,
}
