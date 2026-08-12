from dataclasses import dataclass, field


@dataclass
class FlexmailEndpointConfig:
    path: str
    # `paginated` marks endpoints that accept `limit`/`offset` and wrap results in the HAL
    # collection envelope (`total`/`limit`/`offset`); the rest return the full collection at once.
    paginated: bool = True
    # Flexmail identifiers are account-unique (integers or UUIDs depending on the resource), so
    # `id` is a safe primary key for every endpoint.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Flexmail REST API (https://api.flexmail.eu) list endpoints. All are full-refresh only: no list
# endpoint accepts a server-side timestamp filter (contacts only filter on `email`, custom fields
# on `type`/`language`), so there is no incremental cursor to advance. Contact sub-resources
# (interest subscriptions, preferences, sources per contact) are deliberately not fanned out —
# at 60 requests/minute per account, one request per contact is impractical for real accounts.
FLEXMAIL_ENDPOINTS: dict[str, FlexmailEndpointConfig] = {
    "contacts": FlexmailEndpointConfig(path="/contacts"),
    "custom_fields": FlexmailEndpointConfig(path="/custom-fields", paginated=False),
    "interests": FlexmailEndpointConfig(path="/interests"),
    "opt_in_forms": FlexmailEndpointConfig(path="/opt-in-forms", paginated=False),
    "preferences": FlexmailEndpointConfig(path="/preferences"),
    "segments": FlexmailEndpointConfig(path="/segments", paginated=False),
    "sources": FlexmailEndpointConfig(path="/sources"),
}

ENDPOINTS = tuple(FLEXMAIL_ENDPOINTS.keys())
