from posthog.schema import DatabaseSchemaManagedViewTableKind

from posthog.hogql.database.models import BooleanDatabaseField, DateTimeDatabaseField, StringDatabaseField

from ._definitions import BASE_CURRENCY_FIELDS, FieldsDict, Schema

FIELDS: FieldsDict = {
    "id": StringDatabaseField(name="id"),
    "invoice_item_id": StringDatabaseField(name="invoice_item_id"),
    "source_label": StringDatabaseField(name="source_label"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "created_at": DateTimeDatabaseField(name="created_at"),
    "is_recurring": BooleanDatabaseField(name="is_recurring"),
    "product_id": StringDatabaseField(name="product_id"),
    "customer_id": StringDatabaseField(name="customer_id"),
    "group_0_key": StringDatabaseField(name="group_0_key"),
    "group_1_key": StringDatabaseField(name="group_1_key"),
    "group_2_key": StringDatabaseField(name="group_2_key"),
    "group_3_key": StringDatabaseField(name="group_3_key"),
    "group_4_key": StringDatabaseField(name="group_4_key"),
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
