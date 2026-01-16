from posthog.hogql.database.models import StringDatabaseField

from products.revenue_analytics.backend.views import PRODUCT_ALIAS

from ._definitions import FieldsDict, Schema

FIELDS: FieldsDict = {
    "id": StringDatabaseField(name="id"),
    "source_label": StringDatabaseField(name="source_label"),
    "name": StringDatabaseField(name="name"),
}


SCHEMA = Schema(
    kind=PRODUCT_ALIAS,
    fields=FIELDS,
    source_suffix="product_revenue_view",
    events_suffix="product_events_revenue_view",
)
