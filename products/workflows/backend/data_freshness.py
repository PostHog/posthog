from posthog.data_freshness import DataSourceSpec
from posthog.schema_enums import ProductKey

DATA_SOURCES = [DataSourceSpec(product=ProductKey.WORKFLOWS, app_metrics_source="hog_flow")]
