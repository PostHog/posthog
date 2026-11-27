from typing import TypedDict


class CatchpointEndpoint(TypedDict):
    path: str
    data_selector: str
    primary_keys: list[str]
    paginated: bool


ENDPOINTS: dict[str, CatchpointEndpoint] = {
    "tests": {"path": "tests", "data_selector": "data.tests", "primary_keys": ["id"], "paginated": True},
    "nodes": {"path": "nodes/all", "data_selector": "data.nodes", "primary_keys": ["id"], "paginated": True},
    "products": {"path": "products", "data_selector": "data.products", "primary_keys": ["id"], "paginated": True},
    "folders": {"path": "folders", "data_selector": "data.folders", "primary_keys": ["id"], "paginated": True},
    "divisions": {"path": "divisions", "data_selector": "data.divisions", "primary_keys": ["id"], "paginated": False},
}

API_ROOT = "https://io.catchpoint.com/api"
PAGE_SIZE = 100
AUTH_ERROR = "Catchpoint rejected the API key. Check that the key is valid and has not expired."
PERMISSION_ERROR = "Catchpoint denied access. Check the API consumer's contact permissions and division access."
INCOMPLETE_ERROR = "Catchpoint could not complete the request. Check the API consumer's permissions and try again."
