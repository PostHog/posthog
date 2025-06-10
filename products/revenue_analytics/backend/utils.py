from collections import defaultdict
from posthog.hogql import ast
from posthog.hogql.database.database import Database
from products.revenue_analytics.backend.views import (
    RevenueAnalyticsBaseView,
    RevenueAnalyticsChargeView,
    RevenueAnalyticsCustomerView,
    RevenueAnalyticsInvoiceItemView,
    RevenueAnalyticsProductView,
)

RevenueSelectOutput = defaultdict[str, dict[str, ast.SelectQuery | None]]


def revenue_selects_from_database(database: Database) -> RevenueSelectOutput:
    selects: RevenueSelectOutput = defaultdict(
        lambda: {"charge": None, "customer": None, "invoice_item": None, "product": None}
    )

    for view_name in database.get_views():
        view = database.get_table(view_name)

        if isinstance(view, RevenueAnalyticsBaseView):
            select: ast.SelectQuery | None = None
            if view.source_id is not None:
                select = ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=[view.name])),
                )
            else:
                select = ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=[view.name])),
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
