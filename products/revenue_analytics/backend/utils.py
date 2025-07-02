from collections import defaultdict
from posthog.hogql import ast
from posthog.hogql.database.database import Database
from products.revenue_analytics.backend.views import (
    RevenueAnalyticsBaseView,
    RevenueAnalyticsChargeView,
    RevenueAnalyticsCustomerView,
    RevenueAnalyticsInvoiceItemView,
    RevenueAnalyticsProductView,
    RevenueAnalyticsSubscriptionView,
)

REVENUE_SELECT_OUTPUT_CUSTOMER_KEY = "customer"
REVENUE_SELECT_OUTPUT_INVOICE_ITEM_KEY = "invoice_item"
REVENUE_SELECT_OUTPUT_PRODUCT_KEY = "product"
REVENUE_SELECT_OUTPUT_CHARGE_KEY = "charge"
REVENUE_SELECT_OUTPUT_SUBSCRIPTION_KEY = "subscription"

MAP_FROM_VIEW_TO_KEY = {
    RevenueAnalyticsChargeView: REVENUE_SELECT_OUTPUT_CHARGE_KEY,
    RevenueAnalyticsCustomerView: REVENUE_SELECT_OUTPUT_CUSTOMER_KEY,
    RevenueAnalyticsInvoiceItemView: REVENUE_SELECT_OUTPUT_INVOICE_ITEM_KEY,
    RevenueAnalyticsProductView: REVENUE_SELECT_OUTPUT_PRODUCT_KEY,
    RevenueAnalyticsSubscriptionView: REVENUE_SELECT_OUTPUT_SUBSCRIPTION_KEY,
}

RevenueSelectOutputInnerDict = dict[str, ast.SelectQuery | None]
RevenueSelectOutput = defaultdict[str, RevenueSelectOutputInnerDict]
EMPTY_REVENUE_SELECT_OUTPUT_GENERATOR = lambda: RevenueSelectOutputInnerDict(
    {
        REVENUE_SELECT_OUTPUT_CHARGE_KEY: None,
        REVENUE_SELECT_OUTPUT_CUSTOMER_KEY: None,
        REVENUE_SELECT_OUTPUT_INVOICE_ITEM_KEY: None,
        REVENUE_SELECT_OUTPUT_PRODUCT_KEY: None,
        REVENUE_SELECT_OUTPUT_SUBSCRIPTION_KEY: None,
    }
)


def revenue_selects_from_database(database: Database) -> RevenueSelectOutput:
    selects: RevenueSelectOutput = defaultdict(EMPTY_REVENUE_SELECT_OUTPUT_GENERATOR)

    for view_name in database.get_views():
        view = database.get_table(view_name)

        if isinstance(view, RevenueAnalyticsBaseView):
            view_key = MAP_FROM_VIEW_TO_KEY.get(view.__class__)

            if view_key is not None:
                selects[view.prefix][view_key] = ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=[view.name])),
                )

    return selects
