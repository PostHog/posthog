from typing import TypedDict


class AstronomerEndpoint(TypedDict):
    path: str
    primary_keys: list[str]
    permission: str


BASE_URL = "https://api.astronomer.io/v1/"
PAGE_SIZE = 100
ENDPOINTS: dict[str, AstronomerEndpoint] = {
    "deployments": {
        "path": "deployments",
        "primary_keys": ["id"],
        "permission": "organization.deployments.get",
    },
    "deploys": {
        "path": "deployments/{deployment_id}/deploys",
        "primary_keys": ["deploymentId", "id"],
        "permission": "deployment.deploys.get",
    },
    "workspaces": {
        "path": "workspaces",
        "primary_keys": ["id"],
        "permission": "organization.workspaces.get",
    },
    "clusters": {
        "path": "clusters",
        "primary_keys": ["id"],
        "permission": "organization.clusters.get",
    },
}

AUTH_ERROR = "Astronomer rejected the API token. Check that the token is correct and has not expired."
ACCESS_ERROR = "Astronomer denied access. Check the token permissions and the organization ID."
