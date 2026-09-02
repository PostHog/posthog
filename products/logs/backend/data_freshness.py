from posthog.data_freshness import DataSourceSpec
from posthog.schema_enums import ProductKey

DATA_SOURCES = [DataSourceSpec(product=ProductKey.LOGS, app_metrics_source="logs")]
