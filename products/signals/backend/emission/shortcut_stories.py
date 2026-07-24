"""Signal emitter for shortcut `stories` (record kind: issue).

`created_at` is an ISO string. No status filter: `completed`/`archived` boolean storage is unverified — add `where` once confirmed on a real sync to skip done stories.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ISSUE_ACTIONABILITY_PROMPT, ISSUE_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

SHORTCUT_FIELDS = ("id", "name", "description", "story_type", "labels", "workflow_state_id", "created_at")

SHORTCUT_CONFIG = SignalSourceTableConfig(
    source_product="shortcut",
    source_type="issue",
    emitter=make_flat_emitter(
        source_product="shortcut",
        source_type="issue",
        id_field="id",
        title_field="name",
        body_field="description",
        extra_fields=("story_type", "labels", "workflow_state_id", "created_at"),
        json_list_fields=("labels",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=SHORTCUT_FIELDS,
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=ISSUE_ACTIONABILITY_PROMPT,
    summarization_prompt=ISSUE_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
