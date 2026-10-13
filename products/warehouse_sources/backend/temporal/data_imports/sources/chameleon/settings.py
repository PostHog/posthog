from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen


@frozen
class ChameleonEndpointConfig:
    name: str
    # Path appended to the v3 base URL, e.g. "/analyze/profiles" or "/edit/segments".
    path: str
    # Top-level key in the JSON response that holds the list of records. Chameleon names it after the
    # plural resource (e.g. {"segments": [...], "cursor": {...}}), which matches the endpoint name today.
    data_key: str
    partition_key: Optional[str] = "created_at"  # stable creation timestamp present on every model
    # Chameleon caps `limit` at 500 on the endpoints that document it. `None` marks an endpoint that
    # documents no `limit`, so no `limit` is sent and Chameleon applies its own page size.
    page_size: Optional[int] = 500
    primary_keys: list[str] = field(default_factory=lambda: ["id"])  # Chameleon IDs are globally-unique ObjectIds
    should_sync_default: bool = True
    # Endpoints that require a parent record's `id` query param can only be listed one parent at a
    # time, so this endpoint fans out over every record of the named parent endpoint.
    fan_out_parent: Optional[str] = None
    # Column the parent's id is stamped onto on each child row.
    fan_out_parent_key: Optional[str] = None
    # Values of a required `kind` query param to request in turn, unioned into one table.
    kinds: tuple[str, ...] = ()


CHAMELEON_ENDPOINTS: dict[str, ChameleonEndpointConfig] = {
    # /analyze/profiles is the User Profile search endpoint. Its documented parameters are only
    # `segment_id`, `filters`, `filters_op` and `expand`, with no `limit`, and a request that sends
    # `limit=500` is rejected with 422, which fails the whole table. Without `limit` Chameleon
    # applies its own page size, and the paginator still follows `cursor.before` when the response
    # carries one.
    "profiles": ChameleonEndpointConfig(name="profiles", path="/analyze/profiles", data_key="profiles", page_size=None),
    "companies": ChameleonEndpointConfig(name="companies", path="/analyze/companies", data_key="companies"),
    "segments": ChameleonEndpointConfig(name="segments", path="/edit/segments", data_key="segments"),
    "tours": ChameleonEndpointConfig(name="tours", path="/edit/tours", data_key="tours"),
    "surveys": ChameleonEndpointConfig(name="surveys", path="/edit/surveys", data_key="surveys"),
    "launchers": ChameleonEndpointConfig(name="launchers", path="/edit/launchers", data_key="launchers"),
    "tooltips": ChameleonEndpointConfig(name="tooltips", path="/edit/tooltips", data_key="tooltips"),
    "tags": ChameleonEndpointConfig(name="tags", path="/edit/tags", data_key="tags"),
    "event_names": ChameleonEndpointConfig(name="event_names", path="/edit/event_names", data_key="event_names"),
    # /edit/properties requires `kind` and returns the whole matching set in one un-paginated
    # response, so a complete table means one request per documented kind.
    "properties": ChameleonEndpointConfig(
        name="properties",
        path="/edit/properties",
        data_key="properties",
        kinds=("profile", "company"),
    ),
    # Fan-out child: one paginated request per Microsurvey against /analyze/responses?id=<survey_id>.
    "responses": ChameleonEndpointConfig(
        name="responses",
        path="/analyze/responses",
        data_key="responses",
        fan_out_parent="surveys",
        fan_out_parent_key="survey_id",
    ),
    # Fan-out child: one paginated request per Tour against /analyze/interactions?id=<tour_id>.
    "interactions": ChameleonEndpointConfig(
        name="interactions",
        path="/analyze/interactions",
        data_key="interactions",
        fan_out_parent="tours",
        fan_out_parent_key="tour_id",
    ),
}

ENDPOINTS = tuple(CHAMELEON_ENDPOINTS.keys())
