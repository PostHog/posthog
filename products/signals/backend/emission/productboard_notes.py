"""Signal emitter for productboard `notes` (record kind: feedback).

`createdAt` is an ISO string; notes are raw customer feedback captured in Productboard.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

PRODUCTBOARD_FIELDS = ("id", "title", "content", "state", "tags", "displayUrl", "createdAt")

PRODUCTBOARD_CONFIG = SignalSourceTableConfig(
    source_product="productboard",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="productboard",
        source_type="feedback",
        id_field="id",
        title_field="title",
        body_field="content",
        extra_fields=("state", "tags", "displayUrl", "createdAt"),
        json_list_fields=("tags",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="createdAt",
    partition_field_is_datetime_string=True,
    fields=PRODUCTBOARD_FIELDS,
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
