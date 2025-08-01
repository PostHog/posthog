from typing import Optional
from django.db.models import Prefetch
from posthog.models.team.team import Team
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.hogql import ast
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.database.models import SavedQuery
from posthog.schema import DatabaseSchemaManagedViewTableKind
import re

SUPPORTED_SOURCES: list[ExternalDataSource.Type] = [ExternalDataSource.Type.STRIPE]


class RevenueAnalyticsBaseView(SavedQuery):
    source_id: Optional[str] = None
    prefix: str

    def is_event_view(self) -> bool:
        return self.source_id is None

    @classmethod
    def for_team(cls, team: "Team", timings: HogQLTimings) -> list["RevenueAnalyticsBaseView"]:
        with timings.measure("for_events"):
            for_events = cls.for_events(team)

        with timings.measure("for_schema_source"):
            schema_sources = list(
                ExternalDataSource.objects.filter(team_id=team.pk, source_type__in=SUPPORTED_SOURCES)
                .exclude(deleted=True)
                .prefetch_related(Prefetch("schemas", queryset=ExternalDataSchema.objects.prefetch_related("table")))
            )

            for_schema_sources = [
                view for schema_source in schema_sources for view in cls.for_schema_source(schema_source)
            ]

        return [*for_events, *for_schema_sources]

    @classmethod
    def for_events(cls, team: "Team") -> list["RevenueAnalyticsBaseView"]:
        from .revenue_analytics_charge_view import RevenueAnalyticsChargeView
        from .revenue_analytics_customer_view import RevenueAnalyticsCustomerView
        from .revenue_analytics_invoice_item_view import RevenueAnalyticsInvoiceItemView
        from .revenue_analytics_product_view import RevenueAnalyticsProductView
        from .revenue_analytics_subscription_view import RevenueAnalyticsSubscriptionView

        return [
            *RevenueAnalyticsChargeView.for_events(team),
            *RevenueAnalyticsCustomerView.for_events(team),
            *RevenueAnalyticsInvoiceItemView.for_events(team),
            *RevenueAnalyticsProductView.for_events(team),
            *RevenueAnalyticsSubscriptionView.for_events(team),
        ]

    @classmethod
    def for_schema_source(cls, source: ExternalDataSource) -> list["RevenueAnalyticsBaseView"]:
        from .revenue_analytics_charge_view import RevenueAnalyticsChargeView
        from .revenue_analytics_customer_view import RevenueAnalyticsCustomerView
        from .revenue_analytics_invoice_item_view import RevenueAnalyticsInvoiceItemView
        from .revenue_analytics_product_view import RevenueAnalyticsProductView
        from .revenue_analytics_subscription_view import RevenueAnalyticsSubscriptionView

        return [
            *RevenueAnalyticsChargeView.for_schema_source(source),
            *RevenueAnalyticsCustomerView.for_schema_source(source),
            *RevenueAnalyticsInvoiceItemView.for_schema_source(source),
            *RevenueAnalyticsProductView.for_schema_source(source),
            *RevenueAnalyticsSubscriptionView.for_schema_source(source),
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
        return f"revenue_analytics.events.{re.sub(r'[^a-zA-Z0-9]', '_', event)}"

    # These are generic ways to know how to call/use these views
    @classmethod
    def get_database_schema_table_kind(cls) -> DatabaseSchemaManagedViewTableKind:
        raise NotImplementedError("Subclasses must implement this method")

    @classmethod
    def get_generic_view_alias(cls) -> str:
        return cls.get_database_schema_table_kind().value


def events_expr_for_team(team: Team) -> ast.Expr:
    from posthog.hogql.property import property_to_expr

    exprs = []
    if (
        team.revenue_analytics_config.filter_test_accounts
        and isinstance(team.test_account_filters, list)
        and len(team.test_account_filters) > 0
    ):
        exprs = [property_to_expr(filter, team) for filter in team.test_account_filters]

    if len(exprs) == 0:
        return ast.Constant(value=True)
    elif len(exprs) == 1:
        return exprs[0]
    else:
        return ast.And(exprs=exprs)
