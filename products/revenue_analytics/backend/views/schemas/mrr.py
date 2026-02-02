from posthog.hogql.database.models import DecimalDatabaseField, StringDatabaseField

from products.revenue_analytics.backend.views import MRR_ALIAS

from ._definitions import FieldsDict, Schema

FIELDS: FieldsDict = {
    "source_label": StringDatabaseField(name="source_label"),
    "customer_id": StringDatabaseField(name="customer_id"),
    "subscription_id": StringDatabaseField(name="subscription_id"),
    # Always the MRR at the current time - or when last calculated the materialized view. Doing this by date is too heavy.
    "mrr": DecimalDatabaseField(name="mrr"),
}


SCHEMA = Schema(
    kind=MRR_ALIAS,
    fields=FIELDS,
    source_suffix="mrr_revenue_view",
    events_suffix="mrr_events_revenue_view",
)
