from dataclasses import dataclass, field


@dataclass
class GoogleWebfontsEndpointConfig:
    name: str
    # Path under https://www.googleapis.com.
    path: str
    # Field selecting each row out of the JSON response body.
    data_selector: str = "items"
    primary_keys: list[str] = field(default_factory=lambda: ["family"])
    # Optional `sort` value passed to the API for a deterministic response order.
    sort: str | None = None


# The Google Fonts Developer API exposes a single read-only endpoint that returns the full
# catalog of font families in one (unpaginated) response. There is no server-side timestamp
# filter — each family carries a `lastModified` date but it can't be used to filter the request —
# so this is full refresh only. `family` is the documented globally-unique identifier.
GOOGLE_WEBFONTS_ENDPOINTS: dict[str, GoogleWebfontsEndpointConfig] = {
    "webfonts": GoogleWebfontsEndpointConfig(
        name="webfonts",
        path="/webfonts/v1/webfonts",
        sort="alpha",
    ),
}

ENDPOINTS = tuple(GOOGLE_WEBFONTS_ENDPOINTS.keys())
