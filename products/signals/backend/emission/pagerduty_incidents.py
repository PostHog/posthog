"""Signal emitter for pagerduty `incidents` (record kind: incident).

`status` is triggered, acknowledged, or resolved; `created_at` is an ISO string.
`priority` is not read: it is null on accounts without incident priorities, so the column can be absent.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

PAGERDUTY_FIELDS = (
    "id",
    "title",
    "description",
    "status",
    "urgency",
    "html_url",
    "created_at",
)

PAGERDUTY_CONFIG = SignalSourceTableConfig(
    source_product="pagerduty",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="pagerduty",
        source_type="incident",
        id_field="id",
        title_field="title",
        body_field="description",
        extra_fields=("status", "urgency", "html_url", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=PAGERDUTY_FIELDS,
    where_clause="status != 'resolved'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
