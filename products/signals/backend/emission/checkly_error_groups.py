"""Signal emitter for checkly `error_groups` (record kind: issue).

`cleaned_error_message` is the sanitized message the group is keyed on, so it is the title.
Archived groups (`archived_until_next_event`) are skipped; `first_seen` is an ISO string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

CHECKLY_FIELDS = (
    "id",
    "cleaned_error_message",
    "check_id",
    "error_hash",
    "first_seen",
    "last_seen",
)

CHECKLY_CONFIG = SignalSourceTableConfig(
    source_product="checkly",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="checkly",
        source_type="issue",
        id_field="id",
        title_field="cleaned_error_message",
        extra_fields=("check_id", "error_hash", "first_seen", "last_seen"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="first_seen",
    partition_field_is_datetime_string=True,
    fields=CHECKLY_FIELDS,
    where_clause="NOT ifNull(archived_until_next_event, false)",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
