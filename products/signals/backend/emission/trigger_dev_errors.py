"""Signal emitter for trigger_dev `errors` (record kind: issue).

The table is full-refresh and keyed on (`id`, `task_identifier`), because one fingerprint can group under several tasks.
`status` is unresolved, resolved, or ignored; `first_seen` is an ISO string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

TRIGGER_DEV_FIELDS = (
    "concat(id, ':', task_identifier) AS error_key",
    "coalesce(nullIf(error_type, ''), task_identifier) AS title",
    "error_message",
    "task_identifier",
    "status",
    "count",
    "first_seen",
    "last_seen",
)

TRIGGER_DEV_CONFIG = SignalSourceTableConfig(
    source_product="trigger_dev",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="trigger_dev",
        source_type="issue",
        id_field="error_key",
        title_field="title",
        body_field="error_message",
        extra_fields=("task_identifier", "status", "count", "first_seen", "last_seen"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="first_seen",
    partition_field_is_datetime_string=True,
    fields=TRIGGER_DEV_FIELDS,
    where_clause="coalesce(status, '') NOT IN ('resolved', 'ignored')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
