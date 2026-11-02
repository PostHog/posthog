"""Signal emitter for appsignal `exception_incidents` (record kind: issue).

Each row is an incident that AppSignal already groups from many error samples.
`created_at` is an ISO string and never changes, so the time cursor emits each incident once.
`state` is OPEN, WIP or CLOSED.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

# The headline joins the exception name and message, and uses whichever one is set when the other is empty.
APPSIGNAL_FIELDS = (
    "id",
    "if(ifNull(exception_message, '') = '', ifNull(exception_name, ''), "
    "if(ifNull(exception_name, '') = '', exception_message, "
    "concat(exception_name, ': ', exception_message))) AS headline",
    "first_backtrace_line AS backtrace_line",
    "state",
    "severity",
    "namespace",
    "count AS occurrence_count",
    "created_at",
    "last_occurred_at",
)

APPSIGNAL_CONFIG = SignalSourceTableConfig(
    source_product="appsignal",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="appsignal",
        source_type="issue",
        id_field="id",
        title_field="headline",
        body_field="backtrace_line",
        extra_fields=("state", "severity", "namespace", "occurrence_count", "created_at", "last_occurred_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="toString(created_at)",
    partition_field_is_datetime_string=True,
    fields=APPSIGNAL_FIELDS,
    where_clause="state != 'CLOSED'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
