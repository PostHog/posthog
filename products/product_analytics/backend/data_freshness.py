from posthog.data_freshness import DataSourceSpec
from posthog.schema_enums import ProductKey

# The residual: every event name no other product claims counts as product analytics, so a
# project sending only its own custom events still reads as live.
DATA_SOURCES = [DataSourceSpec(product=ProductKey.PRODUCT_ANALYTICS, is_residual=True)]
