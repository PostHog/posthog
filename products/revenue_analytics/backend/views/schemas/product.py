from posthog.hogql.database.models import StringDatabaseField
from posthog.schema import DatabaseSchemaManagedViewTableKind
from ._definitions import Schema, FieldsDict


FIELDS: FieldsDict = {
    "id": StringDatabaseField(name="id"),
    "source_label": StringDatabaseField(name="source_label"),
    "name": StringDatabaseField(name="name"),
}


SCHEMA = Schema(
    kind=DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_PRODUCT,
    fields=FIELDS,
    source_suffix="product_revenue_view",
    events_suffix="product_events_revenue_view",
)
