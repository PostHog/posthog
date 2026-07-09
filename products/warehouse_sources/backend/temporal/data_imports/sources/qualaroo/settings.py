from dataclasses import dataclass, field


@dataclass
class QualarooEndpointConfig:
    name: str
    path: str
    # Qualaroo nudge (survey) IDs are unique within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Qualaroo REST Reporting API top-level list endpoints. Only account-wide lists are exposed here:
# per-survey responses live at /nudges/{id}/responses.json and require a parent nudge ID, so they
# are a fan-out stream and are intentionally skipped for now.
#
# All endpoints are full-refresh only. The responses endpoint supports server-side start_date/
# end_date filters, but the nudges list has no reliably ordered timestamp filter, so there is no
# incremental cursor to advance (see the implementing-warehouse-sources skill).
QUALAROO_ENDPOINTS: dict[str, QualarooEndpointConfig] = {
    "nudges": QualarooEndpointConfig(name="nudges", path="/nudges.json"),
}

ENDPOINTS = tuple(QUALAROO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
