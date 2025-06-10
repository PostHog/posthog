from collections import defaultdict
from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.schema import RevenueSources
from products.revenue_analytics.backend.views import (
    RevenueAnalyticsBaseView,
    RevenueAnalyticsChargeView,
    RevenueAnalyticsCustomerView,
    RevenueAnalyticsInvoiceItemView,
    RevenueAnalyticsProductView,
)

RevenueSelectOutput = defaultdict[str, dict[str, ast.SelectQuery | None]]


def revenue_selects_from_database(
    database: Database,
    revenue_sources: RevenueSources | None = None,
) -> RevenueSelectOutput:
    selects: RevenueSelectOutput = defaultdict(
        lambda: {"charge": None, "customer": None, "invoice_item": None, "product": None}
    )

    for view_name in database.get_views():
        view = database.get_table(view_name)

        if isinstance(view, RevenueAnalyticsBaseView):
            select: ast.SelectQuery | None = None
            if view.source_id is not None:
                if revenue_sources is None or view.source_id in revenue_sources.dataWarehouseSources:
                    select = ast.SelectQuery(
                        select=[ast.Field(chain=["*"])],
                        select_from=ast.JoinExpr(table=ast.Field(chain=[view.name])),
                    )
            else:
                if revenue_sources is None or len(revenue_sources.events) > 0:
                    select = ast.SelectQuery(
                        select=[ast.Field(chain=["*"])],
                        select_from=ast.JoinExpr(table=ast.Field(chain=[view.name])),
                    )

                    if revenue_sources is not None:
                        select.where = ast.Call(
                            name="in",
                            args=[
                                ast.Field(chain=["event_name"]),
                                ast.Constant(value=revenue_sources.events),
                            ],
                        )

            if isinstance(view, RevenueAnalyticsChargeView):
                selects[view.prefix]["charge"] = select
            elif isinstance(view, RevenueAnalyticsCustomerView):
                selects[view.prefix]["customer"] = select
            elif isinstance(view, RevenueAnalyticsInvoiceItemView):
                selects[view.prefix]["invoice_item"] = select
            elif isinstance(view, RevenueAnalyticsProductView):
                selects[view.prefix]["product"] = select

    return selects
