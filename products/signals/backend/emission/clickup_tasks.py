"""Signal emitter for clickup `tasks` (record kind: issue).

`status` is a nested object, so the query reads its `status` and `type` keys as aliases.
`date_created` is normalized to an ISO string on import. `priority` and `tags` are not read:
`priority` is null on tasks without one, so the column can be absent.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ISSUE_ACTIONABILITY_PROMPT, ISSUE_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

CLICKUP_FIELDS = (
    "id",
    "name",
    "description",
    "JSONExtractString(status, 'status') AS status_name",
    "JSONExtractString(status, 'type') AS status_type",
    "url",
    "date_created",
)

CLICKUP_CONFIG = SignalSourceTableConfig(
    source_product="clickup",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="clickup",
        source_type="issue",
        id_field="id",
        title_field="name",
        body_field="description",
        extra_fields=("status_name", "status_type", "url", "date_created"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="date_created",
    partition_field_is_datetime_string=True,
    fields=CLICKUP_FIELDS,
    where_clause="JSONExtractString(status, 'type') NOT IN ('done', 'closed')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ISSUE_ACTIONABILITY_PROMPT,
    summarization_prompt=ISSUE_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
