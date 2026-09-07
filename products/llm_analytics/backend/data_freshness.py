from posthog.data_freshness import DataSourceSpec
from posthog.schema_enums import ProductKey

# A prefix rather than a list: the `$ai_*` family grows (generation, span, trace, evaluation,
# tag), and any of them means the product is live.
#
# The key is still `llm_analytics`; the product now displays as "AI observability". The UI
# reads that name from onboarding's catalog, so nothing here needs to know about the rename.
DATA_SOURCES = [DataSourceSpec(product=ProductKey.LLM_ANALYTICS, event_prefix="$ai_")]
