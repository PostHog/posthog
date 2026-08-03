"""Signal emitter for rollbar `items` (record kind: issue).

Rollbar timestamps are Unix epoch (seconds); `title` is the item's error title.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

ROLLBAR_FIELDS = ("id", "title", "level", "status", "environment", "framework", "last_occurrence_timestamp")

ROLLBAR_CONFIG = SignalSourceTableConfig(
    source_product="rollbar",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="rollbar",
        source_type="issue",
        id_field="id",
        title_field="title",
        extra_fields=("level", "status", "environment", "framework", "last_occurrence_timestamp"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="fromUnixTimestamp(toUInt32(first_occurrence_timestamp))",
    fields=ROLLBAR_FIELDS,
    where_clause="status != 'resolved'",
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
