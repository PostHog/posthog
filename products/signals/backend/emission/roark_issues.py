"""Signal emitter for roark `issue` (record kind: issue).

`status` is OPEN, ACKED, or RESOLVED and `severity` is LOW, MEDIUM, HIGH, or CRITICAL.
`created_at` is an ISO string; `summary` is the body.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

ROARK_FIELDS = (
    "id",
    "title",
    "summary",
    "severity",
    "status",
    "event_count",
    "created_at",
)

ROARK_CONFIG = SignalSourceTableConfig(
    source_product="roark",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="roark",
        source_type="issue",
        id_field="id",
        title_field="title",
        body_field="summary",
        extra_fields=("severity", "status", "event_count", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=ROARK_FIELDS,
    where_clause="coalesce(status, '') != 'RESOLVED'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
