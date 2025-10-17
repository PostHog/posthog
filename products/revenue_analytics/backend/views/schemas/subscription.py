from posthog.schema import DatabaseSchemaManagedViewTableKind

from posthog.hogql.database.models import DateTimeDatabaseField, StringDatabaseField

from ._definitions import FieldsDict, Schema

FIELDS: FieldsDict = {
    "id": StringDatabaseField(name="id"),
    "source_label": StringDatabaseField(name="source_label"),
    "plan_id": StringDatabaseField(name="plan_id"),
    "product_id": StringDatabaseField(name="product_id"),
    "customer_id": StringDatabaseField(name="customer_id"),
    "status": StringDatabaseField(name="status"),
    "started_at": DateTimeDatabaseField(name="started_at"),
    "ended_at": DateTimeDatabaseField(name="ended_at"),
    "metadata": StringDatabaseField(name="metadata"),
}


SCHEMA = Schema(
    kind=DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_SUBSCRIPTION,
    fields=FIELDS,
    source_suffix="subscription_revenue_view",
    events_suffix="subscription_events_revenue_view",
)
