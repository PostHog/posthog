from dataclasses import dataclass, field


@dataclass
class MentionEndpointConfig:
    name: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Mention API list endpoints (https://dev.mention.com/current/). All are full refresh only:
# mentions do expose a `since_id` server-side cursor, but it orders by fetch recency (not a
# timestamp), and it could not be verified against a live account, so we conservatively ship
# full refresh and rely on merge dedupe (see the implementing-warehouse-sources skill).
MENTION_ENDPOINTS: dict[str, MentionEndpointConfig] = {
    "accounts": MentionEndpointConfig(name="accounts"),
    "alerts": MentionEndpointConfig(name="alerts"),
    # Tag ids are documented as unique identifiers, but uniqueness scope (alert vs account) is not
    # stated, so the parent alert id stays in the composite key.
    "alert_tags": MentionEndpointConfig(name="alert_tags", primary_keys=["alert_id", "id"]),
    # Mentions fan out per alert and each row natively carries `alert_id`; the composite key keeps
    # the same content matched by two alerts as two distinct rows.
    "mentions": MentionEndpointConfig(name="mentions", primary_keys=["alert_id", "id"]),
}

ENDPOINTS = tuple(MENTION_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
