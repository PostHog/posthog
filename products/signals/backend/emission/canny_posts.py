"""Signal emitter for canny `posts` (record kind: feedback).

`created` is an ISO string; `details` is the post body.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

CANNY_FIELDS = ("id", "title", "details", "status", "tags", "score", "voteCount", "url", "created")

CANNY_CONFIG = SignalSourceTableConfig(
    source_product="canny",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="canny",
        source_type="feedback",
        id_field="id",
        title_field="title",
        body_field="details",
        extra_fields=("status", "tags", "score", "voteCount", "url", "created"),
        json_list_fields=("tags",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created",
    partition_field_is_datetime_string=True,
    fields=CANNY_FIELDS,
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
