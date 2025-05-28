from typing import Optional
from posthog.models.team.team import Team
from posthog.hogql.database.models import SavedQuery
from posthog.schema import DatabaseSchemaManagedViewTableKind
from posthog.warehouse.models.external_data_source import ExternalDataSource
import re


class RevenueAnalyticsBaseView(SavedQuery):
    source_id: Optional[str] = None
    prefix: str

    @staticmethod
    def for_events(team: "Team") -> list["RevenueAnalyticsBaseView"]:
        from .revenue_analytics_charge_view import RevenueAnalyticsChargeView
        from .revenue_analytics_customer_view import RevenueAnalyticsCustomerView
        from .revenue_analytics_item_view import RevenueAnalyticsItemView

        return [
            *RevenueAnalyticsChargeView.for_events(team),
            *RevenueAnalyticsCustomerView.for_events(team),
            *RevenueAnalyticsItemView.for_events(team),
        ]

    @staticmethod
    def for_schema_source(source: ExternalDataSource) -> list["RevenueAnalyticsBaseView"]:
        from .revenue_analytics_charge_view import RevenueAnalyticsChargeView
        from .revenue_analytics_customer_view import RevenueAnalyticsCustomerView
        from .revenue_analytics_item_view import RevenueAnalyticsItemView

        return [
            *RevenueAnalyticsChargeView.for_schema_source(source),
            *RevenueAnalyticsCustomerView.for_schema_source(source),
            *RevenueAnalyticsItemView.for_schema_source(source),
        ]

    # Used in child classes to generate view names
    @staticmethod
    def get_view_name_for_source(source: ExternalDataSource, view_name: str) -> str:
        return f"{RevenueAnalyticsBaseView.get_view_prefix_for_source(source)}.{view_name}"

    @staticmethod
    def get_view_name_for_event(event: str, view_name: str) -> str:
        return f"{RevenueAnalyticsBaseView.get_view_prefix_for_event(event)}.{view_name}"

    @staticmethod
    def get_view_prefix_for_source(source: ExternalDataSource) -> str:
        if not source.prefix:
            return source.source_type.lower()
        else:
            prefix = source.prefix.strip("_")
            return f"{source.source_type.lower()}.{prefix}"

    @staticmethod
    def get_view_prefix_for_event(event: str) -> str:
        return f"revenue_analytics.{re.sub(r'[^a-zA-Z0-9]', '_', event)}"

    @staticmethod
    def get_database_schema_table_kind() -> DatabaseSchemaManagedViewTableKind:
        raise NotImplementedError("Subclasses must implement this method")
