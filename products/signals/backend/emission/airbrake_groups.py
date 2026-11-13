"""Signal emitter for airbrake `groups` (record kind: issue).

Each row is an error group that Airbrake already aggregates from many notices.
`created_at` never changes, so the time cursor emits each group once. Resolved groups are skipped.
`errors` is a JSON list of the representative error's causes; the first entry carries the error type and message.
The backtrace is not read.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

_ERROR_TYPE = "JSONExtractString(toString(errors), 1, 'type')"
_ERROR_MESSAGE = "JSONExtractString(toString(errors), 1, 'message')"

# The headline joins the error type and message, and uses whichever one is set when the other is empty.
AIRBRAKE_FIELDS = (
    "id",
    f"if({_ERROR_MESSAGE} = '', {_ERROR_TYPE}, if({_ERROR_TYPE} = '', {_ERROR_MESSAGE}, "
    f"concat({_ERROR_TYPE}, ': ', {_ERROR_MESSAGE}))) AS headline",
    "project_id",
    "JSONExtractString(toString(context), 'environment') AS environment",
    "notice_total_count",
    "created_at",
    "last_notice_at",
)

AIRBRAKE_CONFIG = SignalSourceTableConfig(
    source_product="airbrake",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="airbrake",
        source_type="issue",
        id_field="id",
        title_field="headline",
        extra_fields=("project_id", "environment", "notice_total_count", "created_at", "last_notice_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=AIRBRAKE_FIELDS,
    where_clause="NOT ifNull(resolved, false)",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
