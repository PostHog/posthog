"""The columns a webhook read adds to each event of a table that keeps history.

They are the contract between the webhook read and the history load. The load drops an event whose
`EVENT_ID_COLUMN` it already holds, and orders the versions of a key by `WEBHOOK_EVENT_ORDER`.
"""

# The vendor's event id. An event without one gets a hash of its payload as delivered.
EVENT_ID_COLUMN = "_ph_event_id"
# When the change happened at the vendor, in UTC. It becomes the version's `valid_from`.
EVENT_TIME_COLUMN = "_ph_event_time"
# Orders two events of a key with the same time, such as an invoice's status stage. Higher is newer.
EVENT_RANK_COLUMN = "_ph_event_rank"
# The staged file's `LastModified`, its key and the row's index in it, as text that sorts in arrival order.
ARRIVAL_COLUMN = "_ph_arrival"

WEBHOOK_EVENT_COLUMNS = (EVENT_ID_COLUMN, EVENT_TIME_COLUMN, EVENT_RANK_COLUMN, ARRIVAL_COLUMN)
WEBHOOK_EVENT_ORDER = (EVENT_TIME_COLUMN, EVENT_RANK_COLUMN, ARRIVAL_COLUMN)
