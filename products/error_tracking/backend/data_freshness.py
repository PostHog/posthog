from posthog.data_freshness import DataSourceSpec
from posthog.schema_enums import ProductKey

DATA_SOURCES = [DataSourceSpec(product=ProductKey.ERROR_TRACKING, event_names=("$exception",))]
