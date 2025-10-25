from posthog.schema import DatabaseSchemaManagedViewTableKind

from posthog.hogql.database.models import DateTimeDatabaseField, StringDatabaseField, StringJSONDatabaseField

from ._definitions import FieldsDict, Schema

FIELDS: FieldsDict = {
    "id": StringDatabaseField(name="id"),
    "source_label": StringDatabaseField(name="source_label"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "name": StringDatabaseField(name="name"),
    "email": StringDatabaseField(name="email"),
    "phone": StringDatabaseField(name="phone"),
    "address": StringJSONDatabaseField(name="address"),
    "metadata": StringJSONDatabaseField(name="metadata"),
    "country": StringDatabaseField(name="country"),
    "cohort": StringDatabaseField(name="cohort"),
    "initial_coupon": StringDatabaseField(name="initial_coupon"),
    "initial_coupon_id": StringDatabaseField(name="initial_coupon_id"),
}


SCHEMA = Schema(
    kind=DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER,
    fields=FIELDS,
    source_suffix="customer_revenue_view",
    events_suffix="customer_events_revenue_view",
)
