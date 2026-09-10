"""Signal emitter for gitea `issues` (record kind: issue).

`created_at` is an ISO string; `labels` is a JSON array of label objects.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ISSUE_ACTIONABILITY_PROMPT, ISSUE_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

GITEA_FIELDS = ("id", "title", "body", "state", "labels", "html_url", "number", "created_at")

GITEA_CONFIG = SignalSourceTableConfig(
    source_product="gitea",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="gitea",
        source_type="issue",
        id_field="id",
        title_field="title",
        body_field="body",
        extra_fields=("state", "labels", "html_url", "number", "created_at"),
        json_list_fields=("labels",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=GITEA_FIELDS,
    where_clause="state != 'closed'",
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=ISSUE_ACTIONABILITY_PROMPT,
    summarization_prompt=ISSUE_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
