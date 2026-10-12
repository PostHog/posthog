from typing import TypedDict

API_VERSION = "v1"
BASE_URL = f"https://api.trustradius.com/{API_VERSION}"
API_DOCS_URL = "https://apidocs.trustradius.com/docs/public-api/YXBpOjUxMzgzNjA-trust-radius-api"


class EndpointConfig(TypedDict):
    path: str
    data_selector: str
    primary_keys: list[str]
    partition_key: str | None


ENDPOINTS: dict[str, EndpointConfig] = {
    "products": {
        "path": "product-ids",
        "data_selector": "",
        "primary_keys": ["_id"],
        "partition_key": None,
    },
    "product_scores": {
        "path": "product-scores",
        "data_selector": "products",
        "primary_keys": ["id"],
        "partition_key": None,
    },
    "trustquotes": {
        "path": "trustquotes",
        "data_selector": "",
        "primary_keys": ["id"],
        "partition_key": "created",
    },
    "tags": {
        "path": "tags",
        "data_selector": "",
        "primary_keys": ["id"],
        "partition_key": None,
    },
}

AUTH_ERROR = "TrustRadius rejected your API key. Check the key with your TrustRadius Client Success Manager."
PERMISSION_ERROR = (
    "TrustRadius denied access. Ask your Client Success Manager to check your API license and permissions."
)
NON_RETRYABLE_ERRORS = {
    "401 Client Error": AUTH_ERROR,
    "403 Client Error": PERMISSION_ERROR,
}
