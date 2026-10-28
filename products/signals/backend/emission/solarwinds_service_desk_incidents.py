"""Signal emitter for solarwinds_service_desk `incidents` (record kind: incident).

`category` is a nested object, so the query reads its `name` as `category_name`. `created_at` is an ISO string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

SOLARWINDS_SERVICE_DESK_FIELDS = (
    "id",
    "number",
    "name",
    "description_no_html",
    "state",
    "priority",
    "JSONExtractString(category, 'name') AS category_name",
    "created_at",
)

SOLARWINDS_SERVICE_DESK_CONFIG = SignalSourceTableConfig(
    source_product="solarwinds_service_desk",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="solarwinds_service_desk",
        source_type="incident",
        id_field="id",
        title_field="name",
        body_field="description_no_html",
        extra_fields=("number", "state", "priority", "category_name", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=SOLARWINDS_SERVICE_DESK_FIELDS,
    where_clause="state NOT IN ('Resolved', 'Closed')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
