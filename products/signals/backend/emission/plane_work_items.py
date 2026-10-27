"""Signal emitter for plane `work_items` (record kind: issue).

The synced table has no description column, so the work item name is the whole text.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ISSUE_ACTIONABILITY_PROMPT, ISSUE_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

PLANE_FIELDS = (
    "id",
    "name",
    "identifier",
    "sequence_id",
    "priority",
    "created_at",
)

PLANE_CONFIG = SignalSourceTableConfig(
    source_product="plane",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="plane",
        source_type="issue",
        id_field="id",
        title_field="name",
        extra_fields=("identifier", "sequence_id", "priority", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=PLANE_FIELDS,
    where_clause="isNull(completed_at) AND isNull(archived_at)",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ISSUE_ACTIONABILITY_PROMPT,
    summarization_prompt=ISSUE_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
