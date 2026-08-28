"""Signal emitter for raygun `error_groups` (record kind: issue).

`createdAt` is an ISO string; the record id column is `identifier`.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

RAYGUN_FIELDS = ("identifier", "message", "status", "applicationUrl", "lastOccurredAt", "createdAt")

RAYGUN_CONFIG = SignalSourceTableConfig(
    source_product="raygun",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="raygun",
        source_type="issue",
        id_field="identifier",
        title_field="message",
        extra_fields=("status", "applicationUrl", "lastOccurredAt", "createdAt"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="createdAt",
    partition_field_is_datetime_string=True,
    fields=RAYGUN_FIELDS,
    where_clause="status = 'active'",
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
