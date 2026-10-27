"""Signal emitter for trello `cards` (record kind: issue).

The import snake_cases the API names, so `idBoard` is `id_board`. `created_at` is derived from
the card id and is an ISO string. The import fetches open cards only, so there is no status filter.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ISSUE_ACTIONABILITY_PROMPT, ISSUE_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

TRELLO_FIELDS = (
    "id",
    "name",
    "desc",
    "url",
    "id_board",
    "id_list",
    "created_at",
)

TRELLO_CONFIG = SignalSourceTableConfig(
    source_product="trello",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="trello",
        source_type="issue",
        id_field="id",
        title_field="name",
        body_field="desc",
        extra_fields=("url", "id_board", "id_list", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=TRELLO_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ISSUE_ACTIONABILITY_PROMPT,
    summarization_prompt=ISSUE_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
