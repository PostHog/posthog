from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChameleonEndpointConfig:
    name: str
    # Path appended to the v3 base URL, e.g. "/analyze/profiles" or "/edit/segments".
    path: str
    # Top-level key in the JSON response that holds the list of records. Chameleon names it after the
    # plural resource (e.g. {"segments": [...], "cursor": {...}}), which matches the endpoint name today.
    data_key: str
    partition_key: Optional[str] = "created_at"  # stable creation timestamp present on every model
    page_size: int = 500  # Chameleon caps `limit` at 500
    primary_keys: list[str] = field(default_factory=lambda: ["id"])  # Chameleon IDs are globally-unique ObjectIds
    should_sync_default: bool = True
    # Microsurvey responses can only be listed per-survey (the `id` param is required), so this endpoint
    # fans out over every Microsurvey and stamps the parent `survey_id` onto each row.
    fan_out_over_surveys: bool = False


CHAMELEON_ENDPOINTS: dict[str, ChameleonEndpointConfig] = {
    "profiles": ChameleonEndpointConfig(name="profiles", path="/analyze/profiles", data_key="profiles"),
    "companies": ChameleonEndpointConfig(name="companies", path="/analyze/companies", data_key="companies"),
    "segments": ChameleonEndpointConfig(name="segments", path="/edit/segments", data_key="segments"),
    "tours": ChameleonEndpointConfig(name="tours", path="/edit/tours", data_key="tours"),
    "surveys": ChameleonEndpointConfig(name="surveys", path="/edit/surveys", data_key="surveys"),
    "launchers": ChameleonEndpointConfig(name="launchers", path="/edit/launchers", data_key="launchers"),
    "event_names": ChameleonEndpointConfig(name="event_names", path="/edit/event_names", data_key="event_names"),
    # Fan-out child: one paginated request per Microsurvey against /analyze/responses?id=<survey_id>.
    "responses": ChameleonEndpointConfig(
        name="responses",
        path="/analyze/responses",
        data_key="responses",
        fan_out_over_surveys=True,
    ),
}

ENDPOINTS = tuple(CHAMELEON_ENDPOINTS.keys())
