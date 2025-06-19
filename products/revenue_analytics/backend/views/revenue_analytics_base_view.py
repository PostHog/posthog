from typing import Optional
from posthog.models.team.team import Team
from posthog.hogql import ast
from posthog.hogql.database.models import SavedQuery
from posthog.schema import DatabaseSchemaManagedViewTableKind
from posthog.warehouse.models.external_data_source import ExternalDataSource
import re


class RevenueAnalyticsBaseView(SavedQuery):
    source_id: Optional[str] = None
    prefix: str

    @classmethod
    def for_events(cls, team: "Team") -> list["RevenueAnalyticsBaseView"]:
        from .revenue_analytics_charge_view import RevenueAnalyticsChargeView
        from .revenue_analytics_customer_view import RevenueAnalyticsCustomerView
        from .revenue_analytics_invoice_item_view import RevenueAnalyticsInvoiceItemView
        from .revenue_analytics_product_view import RevenueAnalyticsProductView

        return [
            *RevenueAnalyticsChargeView.for_events(team),
            *RevenueAnalyticsCustomerView.for_events(team),
            *RevenueAnalyticsInvoiceItemView.for_events(team),
            *RevenueAnalyticsProductView.for_events(team),
        ]

    @classmethod
    def for_schema_source(cls, source: ExternalDataSource) -> list["RevenueAnalyticsBaseView"]:
        from .revenue_analytics_charge_view import RevenueAnalyticsChargeView
        from .revenue_analytics_customer_view import RevenueAnalyticsCustomerView
        from .revenue_analytics_invoice_item_view import RevenueAnalyticsInvoiceItemView
        from .revenue_analytics_product_view import RevenueAnalyticsProductView

        return [
            *RevenueAnalyticsChargeView.for_schema_source(source),
            *RevenueAnalyticsCustomerView.for_schema_source(source),
            *RevenueAnalyticsInvoiceItemView.for_schema_source(source),
            *RevenueAnalyticsProductView.for_schema_source(source),
        ]

    # Used in child classes to generate view names
    @classmethod
    def get_view_name_for_source(cls, source: ExternalDataSource, view_name: str) -> str:
        return f"{cls.get_view_prefix_for_source(source)}.{view_name}"

    @classmethod
    def get_view_name_for_event(cls, event: str, view_name: str) -> str:
        return f"{cls.get_view_prefix_for_event(event)}.{view_name}"

    @classmethod
    def get_view_prefix_for_source(cls, source: ExternalDataSource) -> str:
        if not source.prefix:
            return source.source_type.lower()
        else:
            prefix = source.prefix.strip("_")
            return f"{source.source_type.lower()}.{prefix}"

    @classmethod
    def get_view_prefix_for_event(cls, event: str) -> str:
        return f"revenue_analytics.{re.sub(r'[^a-zA-Z0-9]', '_', event)}"

    # These are generic ways to know how to call/use these views
    @classmethod
    def get_database_schema_table_kind(cls) -> DatabaseSchemaManagedViewTableKind:
        raise NotImplementedError("Subclasses must implement this method")

    @classmethod
    def get_generic_view_alias(cls) -> str:
        return cls.get_database_schema_table_kind().value


def events_exprs_for_team(team: Team) -> list[ast.Expr]:
    from posthog.hogql.property import property_to_expr

    if (
        team.revenue_analytics_config.filter_test_accounts
        and isinstance(team.test_account_filters, list)
        and len(team.test_account_filters) > 0
    ):
        return [property_to_expr(filter, team) for filter in team.test_account_filters]
    else:
        return []
