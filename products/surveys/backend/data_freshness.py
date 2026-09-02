from posthog.data_freshness import DataSourceSpec
from posthog.schema_enums import ProductKey

from products.surveys.backend.util import SurveyEventName

DATA_SOURCES = [
    DataSourceSpec(
        product=ProductKey.SURVEYS,
        event_names=(SurveyEventName.SHOWN, SurveyEventName.DISMISSED, SurveyEventName.SENT),
    )
]
