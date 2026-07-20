from dataclasses import dataclass, field


@dataclass
class SimplesatEndpointConfig:
    name: str
    path: str
    # Simplesat list responses wrap records under a key named after the resource
    # (e.g. {"surveys": [...], "next": ...}), so the extraction key is per-endpoint.
    list_key: str
    # A few list endpoints are exposed only as POST `/<resource>/search` collection endpoints.
    method: str = "GET"
    # Simplesat object IDs are unique per account, so `id` is a safe primary key everywhere.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Simplesat v1 top-level list endpoints. All are full-refresh only: while `answers` and
# `responses` accept optional start_date/end_date filters, the API's ordering guarantees for
# those filters aren't documented well enough to advance an incremental cursor safely, so a
# client-side scan would cost the same as a full refresh (see the implementing-warehouse-sources
# skill).
SIMPLESAT_ENDPOINTS: dict[str, SimplesatEndpointConfig] = {
    "surveys": SimplesatEndpointConfig(name="surveys", path="/surveys", list_key="surveys", method="GET"),
    "questions": SimplesatEndpointConfig(name="questions", path="/questions", list_key="questions", method="GET"),
    "answers": SimplesatEndpointConfig(name="answers", path="/answers/search", list_key="answers", method="POST"),
    "responses": SimplesatEndpointConfig(
        name="responses", path="/responses/search", list_key="responses", method="POST"
    ),
}

ENDPOINTS = tuple(SIMPLESAT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
