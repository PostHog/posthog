"""Signal emitter for dynamics365 `Cases` (record kind: ticket).

`statecode` 0 is an active case (1 is resolved, 2 is cancelled); `createdon` is an ISO string.
Customer, contact and owner lookup columns are not read because they identify people.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import TICKET_ACTIONABILITY_PROMPT, TICKET_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

DYNAMICS365_FIELDS = (
    "incidentid",
    "ticketnumber",
    "title",
    "description",
    "prioritycode",
    "severitycode",
    "casetypecode",
    "statuscode",
    "createdon",
)

DYNAMICS365_CONFIG = SignalSourceTableConfig(
    source_product="dynamics365",
    source_type="ticket",
    emitter=make_flat_emitter(
        source_product="dynamics365",
        source_type="ticket",
        id_field="incidentid",
        title_field="title",
        body_field="description",
        extra_fields=("ticketnumber", "prioritycode", "severitycode", "casetypecode", "statuscode", "createdon"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="createdon",
    partition_field_is_datetime_string=True,
    fields=DYNAMICS365_FIELDS,
    where_clause="statecode = 0",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=TICKET_ACTIONABILITY_PROMPT,
    summarization_prompt=TICKET_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
