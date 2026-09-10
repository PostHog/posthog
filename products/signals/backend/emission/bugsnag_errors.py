"""Signal emitter for bugsnag `errors` (record kind: issue).

`first_seen` is an ISO string; description combines the error class and message.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

BUGSNAG_FIELDS = ("id", "error_class", "message", "severity", "status", "context", "first_seen", "last_seen")

BUGSNAG_CONFIG = SignalSourceTableConfig(
    source_product="bugsnag",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="bugsnag",
        source_type="issue",
        id_field="id",
        title_field="error_class",
        body_field="message",
        extra_fields=("severity", "status", "context", "first_seen", "last_seen"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="first_seen",
    partition_field_is_datetime_string=True,
    fields=BUGSNAG_FIELDS,
    where_clause="status NOT IN ('fixed', 'ignored')",
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
