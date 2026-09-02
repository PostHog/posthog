from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ButtondownEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Server-side "created on/after" filter, when the endpoint has one. Only endpoints that expose
    # it advertise incremental sync; the rest are full refresh.
    incremental_start_param: str | None = None
    # Value passed as `?ordering=`. Only set where the API documents `creation_date` as an accepted
    # ordering value, so pagination walks a stable, monotonic column.
    ordering: str | None = None
    # Only consulted on incremental syncs: "asc" lets the pipeline checkpoint the watermark after
    # every batch, so it is safe only where the request forces ascending order. Endpoints whose
    # order we cannot force stay "desc", which defers the commit to the end of a successful job.
    sort_mode: SortMode = "desc"
    partition_key: str | None = "creation_date"


BUTTONDOWN_ENDPOINTS: dict[str, ButtondownEndpointConfig] = {
    "automations": ButtondownEndpointConfig(name="automations", path="/automations", sort_mode="asc"),
    "comments": ButtondownEndpointConfig(name="comments", path="/comments", ordering="creation_date", sort_mode="asc"),
    "emails": ButtondownEndpointConfig(
        name="emails",
        path="/emails",
        incremental_start_param="creation_date__start",
        ordering="creation_date",
        sort_mode="asc",
    ),
    "events": ButtondownEndpointConfig(name="events", path="/events", ordering="creation_date", sort_mode="asc"),
    "forms": ButtondownEndpointConfig(name="forms", path="/forms", ordering="creation_date", sort_mode="asc"),
    "prices": ButtondownEndpointConfig(name="prices", path="/prices", sort_mode="asc", partition_key=None),
    # `ordering` is documented on /subscribers but its accepted values are not enumerated, and an
    # unrecognized value falls back to the default `-creation_date` rather than erroring. Rather
    # than risk declaring an ascending sort the API silently ignores, take the documented default
    # (newest first) and keep the watermark on the end-of-job commit path.
    "subscribers": ButtondownEndpointConfig(
        name="subscribers", path="/subscribers", incremental_start_param="date__start"
    ),
    # /survey_responses has no `ordering` param at all, so row order is undocumented.
    "survey_responses": ButtondownEndpointConfig(
        name="survey_responses", path="/survey_responses", incremental_start_param="creation_date__start"
    ),
    "surveys": ButtondownEndpointConfig(name="surveys", path="/surveys", ordering="creation_date", sort_mode="asc"),
    "tags": ButtondownEndpointConfig(name="tags", path="/tags", sort_mode="asc"),
}

ENDPOINTS = tuple(BUTTONDOWN_ENDPOINTS.keys())

# Only endpoints with a real server-side "created on/after" filter. Everything else stays full
# refresh: /events and /comments carry a `creation_date` but expose no date filter, so an
# "incremental" sync there would still page through the entire history on every run.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": "creation_date",
            "type": IncrementalFieldType.DateTime,
            "field": "creation_date",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for name, config in BUTTONDOWN_ENDPOINTS.items()
    if config.incremental_start_param is not None
}
