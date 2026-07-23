"""Signal emitter for sentry `issues` (record kind: issue).

`firstSeen` is an ISO string; `culprit` names the failing code path.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

SENTRY_FIELDS = ("id", "title", "culprit", "level", "status", "permalink", "shortId", "firstSeen")

SENTRY_CONFIG = SignalSourceTableConfig(
    source_product="sentry",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="sentry",
        source_type="issue",
        id_field="id",
        title_field="title",
        body_field="culprit",
        extra_fields=("level", "status", "permalink", "shortId", "firstSeen"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="firstSeen",
    partition_field_is_datetime_string=True,
    fields=SENTRY_FIELDS,
    where_clause="status NOT IN ('resolved', 'ignored')",
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
