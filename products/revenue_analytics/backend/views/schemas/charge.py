from posthog.schema import DatabaseSchemaManagedViewTableKind

from posthog.hogql.database.models import DateTimeDatabaseField, StringDatabaseField

from ._definitions import BASE_CURRENCY_FIELDS, FieldsDict, Schema

FIELDS: FieldsDict = {
    "id": StringDatabaseField(name="id"),
    "source_label": StringDatabaseField(name="source_label"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "customer_id": StringDatabaseField(name="customer_id"),
    "invoice_id": StringDatabaseField(name="invoice_id"),
    "session_id": StringDatabaseField(name="session_id"),
    "event_name": StringDatabaseField(name="event_name"),
    **BASE_CURRENCY_FIELDS,
}


SCHEMA = Schema(
    kind=DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CHARGE,
    fields=FIELDS,
    source_suffix="charge_revenue_view",
    events_suffix="charge_events_revenue_view",
)
