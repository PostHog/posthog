from typing import Optional
from posthog.models.team.team import Team
from posthog.hogql.database.models import SavedQuery
from posthog.warehouse.models.external_data_source import ExternalDataSource


class RevenueAnalyticsBaseView(SavedQuery):
    source_id: Optional[str] = None

    @staticmethod
    def for_events(team: "Team") -> list["RevenueAnalyticsBaseView"]:
        from .revenue_analytics_charge_view import RevenueAnalyticsChargeView
        from .revenue_analytics_customer_view import RevenueAnalyticsCustomerView

        return [
            *RevenueAnalyticsChargeView.for_events(team),
            *RevenueAnalyticsCustomerView.for_events(team),
        ]

    @staticmethod
    def for_schema_source(source: ExternalDataSource) -> list["RevenueAnalyticsBaseView"]:
        from .revenue_analytics_charge_view import RevenueAnalyticsChargeView
        from .revenue_analytics_customer_view import RevenueAnalyticsCustomerView

        return [
            *RevenueAnalyticsChargeView.for_schema_source(source),
            *RevenueAnalyticsCustomerView.for_schema_source(source),
        ]

    # Used in child classes to generate the view name
    @staticmethod
    def get_view_name_for_source(source: ExternalDataSource, view_name: str) -> str:
        if not source.prefix:
            return f"{source.source_type.lower()}.{view_name}"
        else:
            prefix = source.prefix.strip("_")
            return f"{source.source_type.lower()}.{prefix}.{view_name}"
