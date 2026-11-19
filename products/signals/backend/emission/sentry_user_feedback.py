"""Signal emitter for Sentry `project_user_feedback` (record kind: feedback).

Each row is a user report attached to an error event. `comments` is the only text, so it is the
title. `name`, `email` and `user` identify the reporter and are not selected. The nested `issue`
object is null until Sentry links the report to an issue, so it is not selected either.

The product is `sentry_feedback`, not `sentry`, so this table has its own toggle and the
existing Sentry issues toggle (`sentry`, `issue`) does not change.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

SENTRY_FEEDBACK_FIELDS = ("id", "comments", "project_slug", "event_id", "date_created")

SENTRY_FEEDBACK_CONFIG = SignalSourceTableConfig(
    source_product="sentry_feedback",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="sentry_feedback",
        source_type="feedback",
        id_field="id",
        title_field="comments",
        extra_fields=("project_slug", "event_id", "date_created"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="date_created",
    partition_field_is_datetime_string=True,
    fields=SENTRY_FEEDBACK_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
