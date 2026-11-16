"""Signal emitter for servicenow `incidents` (record kind: incident).

The Table API returns raw values, so `state` is a numeric string (6=Resolved, 7=Closed, 8=Canceled).
`sys_created_on` is a `YYYY-MM-DD HH:MM:SS` string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

SERVICENOW_FIELDS = (
    "sys_id",
    "number",
    "short_description",
    "description",
    "state",
    "priority",
    "urgency",
    "impact",
    "category",
    "sys_created_on",
)

SERVICENOW_CONFIG = SignalSourceTableConfig(
    source_product="servicenow",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="servicenow",
        source_type="incident",
        id_field="sys_id",
        title_field="short_description",
        body_field="description",
        extra_fields=("number", "state", "priority", "urgency", "impact", "category", "sys_created_on"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="sys_created_on",
    partition_field_is_datetime_string=True,
    fields=SERVICENOW_FIELDS,
    where_clause="state NOT IN ('6', '7', '8')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
