from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    StringDatabaseField,
)
from posthog.schema import DatabaseSchemaManagedViewTableKind
from ._definitions import BASE_CURRENCY_FIELDS, Schema, FieldsDict


FIELDS: FieldsDict = {
    "id": StringDatabaseField(name="id"),
    "invoice_item_id": StringDatabaseField(name="invoice_item_id"),
    "source_label": StringDatabaseField(name="source_label"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "created_at": DateTimeDatabaseField(name="created_at"),
    "is_recurring": BooleanDatabaseField(name="is_recurring"),
    "product_id": StringDatabaseField(name="product_id"),
    "customer_id": StringDatabaseField(name="customer_id"),
    "invoice_id": StringDatabaseField(name="invoice_id"),
    "subscription_id": StringDatabaseField(name="subscription_id"),
    "session_id": StringDatabaseField(name="session_id"),
    "event_name": StringDatabaseField(name="event_name"),
    "coupon": StringDatabaseField(name="coupon"),
    "coupon_id": StringDatabaseField(name="coupon_id"),
    **BASE_CURRENCY_FIELDS,
}


SCHEMA = Schema(
    kind=DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM,
    fields=FIELDS,
    source_suffix="revenue_item_revenue_view",
    events_suffix="revenue_item_events_revenue_view",
)
