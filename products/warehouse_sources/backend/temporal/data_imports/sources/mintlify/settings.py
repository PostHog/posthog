from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://api.mintlify.com"
API_VERSION = "v1"


@frozen
class MintlifyEndpoint:
    path: str
    data_selector: str
    primary_keys: tuple[str, ...]
    limit: int
    offset_pagination: bool = False


ENDPOINTS = {
    # A conversation can contain several turns. Their timestamps distinguish rows with the same conversation identifier.
    "assistant_conversations": MintlifyEndpoint(
        path="assistant", data_selector="conversations", primary_keys=("id", "timestamp"), limit=1000
    ),
    "feedback": MintlifyEndpoint(path="feedback", data_selector="feedback", primary_keys=("id",), limit=100),
    "searches": MintlifyEndpoint(path="searches", data_selector="searches", primary_keys=("searchQuery",), limit=100),
    "views": MintlifyEndpoint(
        path="views", data_selector="views", primary_keys=("path",), limit=250, offset_pagination=True
    ),
    "visitors": MintlifyEndpoint(
        path="visitors", data_selector="visitors", primary_keys=("path",), limit=250, offset_pagination=True
    ),
}

# Aggregates need complete replacements. Feedback has mutable status but no modification timestamp.
INCREMENTAL_FIELDS = {"assistant_conversations": [incremental_field("timestamp")]}

AUTH_ERROR = "Your Mintlify API key is invalid or expired. Create an admin API key and reconnect."
ACCESS_ERROR = "Mintlify denied access. Check your admin API key, project ID, and Pro or Enterprise plan."
PROJECT_ERROR = "Mintlify could not find this project. Copy the project ID from the API keys page."
HTTP_ERRORS = {401: AUTH_ERROR, 403: ACCESS_ERROR, 404: PROJECT_ERROR}
