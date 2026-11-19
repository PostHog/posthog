"""Signal emitter for wrike `tasks` (record kind: issue).

The import snake_cases the API names, so `createdDate` is `created_date`. It is an ISO string.
`description` is not selected: Wrike's `/tasks` list only returns it when the request opts in via
`fields`, and the import does not, so the column is absent from synced tables. Signals carry the title only.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ISSUE_ACTIONABILITY_PROMPT, ISSUE_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

WRIKE_FIELDS = (
    "id",
    "title",
    "status",
    "importance",
    "permalink",
    "created_date",
)

WRIKE_CONFIG = SignalSourceTableConfig(
    source_product="wrike",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="wrike",
        source_type="issue",
        id_field="id",
        title_field="title",
        extra_fields=("status", "importance", "permalink", "created_date"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_date",
    partition_field_is_datetime_string=True,
    fields=WRIKE_FIELDS,
    where_clause="status NOT IN ('Completed', 'Cancelled')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ISSUE_ACTIONABILITY_PROMPT,
    summarization_prompt=ISSUE_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
