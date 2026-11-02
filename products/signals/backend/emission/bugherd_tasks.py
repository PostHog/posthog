"""Signal emitter for bugherd `Tasks` (record kind: issue).

The table name is capitalized, as the import names it. `created_at` is an ISO string.
The requester columns are not read, because they identify a person.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ISSUE_ACTIONABILITY_PROMPT, ISSUE_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

BUGHERD_FIELDS = (
    "id",
    "title",
    "description",
    "status",
    "priority",
    "site",
    "url",
    "tag_names",
    "created_at",
)

BUGHERD_CONFIG = SignalSourceTableConfig(
    source_product="bugherd",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="bugherd",
        source_type="issue",
        id_field="id",
        title_field="title",
        body_field="description",
        extra_fields=("status", "priority", "site", "url", "tag_names", "created_at"),
        json_list_fields=("tag_names",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=BUGHERD_FIELDS,
    where_clause="status != 'closed'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ISSUE_ACTIONABILITY_PROMPT,
    summarization_prompt=ISSUE_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
