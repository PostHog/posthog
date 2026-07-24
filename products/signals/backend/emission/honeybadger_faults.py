"""Signal emitter for honeybadger `faults` (record kind: issue).

`created_at` is an ISO string. No status filter: `resolved`/`ignored` boolean storage is unverified — add `where` once confirmed on a real sync.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

HONEYBADGER_FIELDS = ("id", "klass", "message", "environment", "component", "action", "tags", "url", "created_at")

HONEYBADGER_CONFIG = SignalSourceTableConfig(
    source_product="honeybadger",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="honeybadger",
        source_type="issue",
        id_field="id",
        title_field="klass",
        body_field="message",
        extra_fields=("environment", "component", "action", "tags", "url", "created_at"),
        json_list_fields=("tags",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=HONEYBADGER_FIELDS,
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
