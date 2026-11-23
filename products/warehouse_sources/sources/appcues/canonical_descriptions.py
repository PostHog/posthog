from products.warehouse_sources.sources.appcues.settings import ENDPOINTS
from products.warehouse_sources.sources.sdk import CanonicalDescriptions

RECORD_COLUMNS = {
    "id": "Unique identifier for this record within the Appcues account.",
    "created_at": "Time when the record was created.",
    "updated_at": "Time when the record was last changed.",
    "created_by": "Identifier of the user who created the record.",
    "updated_by": "Identifier of the user who last changed the record.",
}

TABLE_COLUMNS = {
    "ingestion_filtering_rules": {
        "account_id": "Appcues account ID.",
        "type": "Whether the rules allow or deny the listed names: allow, deny, allow_pattern, or deny_pattern.",
        "profile_rules": "Profile attribute names or patterns that the rules allow or deny.",
        "event_rules": "Event names or patterns that the rules allow or deny.",
        "group_rules": "Group attribute names or patterns that the rules allow or deny.",
    },
    "events": {
        "name": "Event name, such as appcues:flow_started or a custom event name.",
        "timestamp": "Time when the event happened, in UTC.",
        "user_id": "ID of the user who triggered the event.",
        "attributes": "All other data about the event, such as the flow ID and step ID.",
    },
    "segment_membership": {
        "segment_id": "ID of the segment.",
        "user_id": "ID of a user who is a member of the segment.",
    },
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    name: {
        "description": endpoint.description,
        "docs_url": f"https://api.appcues.com/v2/docs#{endpoint.docs_anchor}",
        "columns": TABLE_COLUMNS.get(name, RECORD_COLUMNS),
    }
    for name, endpoint in ENDPOINTS.items()
}
