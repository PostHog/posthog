"""Signal emitter for hubspot `tickets` (record kind: ticket).

HubSpot is an OAuth-connected source, but its `tickets` table is flat, so the shared factory
applies. `hs_object_id` is the record id, `subject`/`content` the text, `createdate` an ISO
string. Only the ticket properties the user selected during setup are synced; the defaults
include subject/content/createdate.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import TICKET_ACTIONABILITY_PROMPT, TICKET_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

HUBSPOT_FIELDS = (
    "hs_object_id",
    "subject",
    "content",
    "hs_ticket_priority",
    "hs_pipeline_stage",
    "hs_ticket_category",
    "createdate",
)

HUBSPOT_CONFIG = SignalSourceTableConfig(
    source_product="hubspot",
    source_type="ticket",
    emitter=make_flat_emitter(
        source_product="hubspot",
        source_type="ticket",
        id_field="hs_object_id",
        title_field="subject",
        body_field="content",
        extra_fields=("hs_ticket_priority", "hs_pipeline_stage", "hs_ticket_category", "createdate"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="createdate",
    partition_field_is_datetime_string=True,
    fields=HUBSPOT_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=TICKET_ACTIONABILITY_PROMPT,
    summarization_prompt=TICKET_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
