from posthog.schema import DatabaseSchemaManagedViewTableKind

from posthog.hogql.database.models import DecimalDatabaseField, StringDatabaseField

from ._definitions import FieldsDict, Schema

# How many days to look back to calculate MRR, needs to be at least 30 to get all
# of the subscriptions from the previous period. Erring on the side of caution here.
LOOKBACK_PERIOD_DAYS = 60

FIELDS: FieldsDict = {
    "source_label": StringDatabaseField(name="source_label"),
    "customer_id": StringDatabaseField(name="customer_id"),
    "subscription_id": StringDatabaseField(name="subscription_id"),
    # Always the MRR right now - or when last calculated the materialized view. Doing this by date is too heavy.
    "mrr": DecimalDatabaseField(name="mrr"),
}


SCHEMA = Schema(
    kind=DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_MRR,
    fields=FIELDS,
    source_suffix="mrr_revenue_view",
    events_suffix="mrr_events_revenue_view",
)
