"""Signal emitter for zenduty `incidents` (record kind: incident).

`unique_id` is the incident id and `title` its text. `creation_date` is an ISO string.
`status` and `urgency` are passed through as they are stored, without a filter on their values.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

ZENDUTY_FIELDS = (
    "unique_id",
    "title",
    "incident_number",
    "status",
    "urgency",
    "creation_date",
)

ZENDUTY_CONFIG = SignalSourceTableConfig(
    source_product="zenduty",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="zenduty",
        source_type="incident",
        id_field="unique_id",
        title_field="title",
        extra_fields=("incident_number", "status", "urgency", "creation_date"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="creation_date",
    partition_field_is_datetime_string=True,
    fields=ZENDUTY_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
