"""Signal emitter for gitlab `issues` (record kind: issue).

`created_at` is an ISO string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ISSUE_ACTIONABILITY_PROMPT, ISSUE_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

GITLAB_FIELDS = ("id", "title", "description", "state", "labels", "iid", "project_id", "created_at")

GITLAB_CONFIG = SignalSourceTableConfig(
    source_product="gitlab",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="gitlab",
        source_type="issue",
        id_field="id",
        title_field="title",
        body_field="description",
        extra_fields=("state", "labels", "iid", "project_id", "created_at"),
        json_list_fields=("labels",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=GITLAB_FIELDS,
    where_clause="state != 'closed'",
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=ISSUE_ACTIONABILITY_PROMPT,
    summarization_prompt=ISSUE_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
