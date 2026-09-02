from posthog.data_freshness import DataSourceSpec
from posthog.schema_enums import ProductKey

# Flag evaluations, not flag edits: a project with flags configured but nothing calling them
# is not receiving data.
DATA_SOURCES = [DataSourceSpec(product=ProductKey.FEATURE_FLAGS, event_names=("$feature_flag_called",))]
