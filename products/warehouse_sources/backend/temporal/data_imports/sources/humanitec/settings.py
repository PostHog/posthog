from typing import Literal

from posthog.dataclasses import frozen

API_BASE_URL = "https://api.humanitec.io/"
API_DOCS_URL = "https://api-docs.humanitec.com/"


@frozen
class HumanitecEndpoint:
    path: str
    primary_keys: tuple[str, ...]
    parent: Literal["applications", "application_environments"] | None = None
    paginated: bool = False


ENDPOINTS: dict[str, HumanitecEndpoint] = {
    "applications": HumanitecEndpoint(path="apps", primary_keys=("id",)),
    "environments": HumanitecEndpoint(path="apps/{app_id}/envs", primary_keys=("app_id", "id"), parent="applications"),
    "deployments": HumanitecEndpoint(
        path="apps/{app_id}/envs/{env_id}/deploys",
        primary_keys=("app_id", "env_id", "id"),
        parent="application_environments",
    ),
    "active_resources": HumanitecEndpoint(
        path="apps/{app_id}/envs/{env_id}/resources",
        primary_keys=("app_id", "env_id", "gu_res_id"),
        parent="application_environments",
    ),
    "environment_types": HumanitecEndpoint(path="env-types", primary_keys=("id",)),
    "pipelines": HumanitecEndpoint(
        path="apps/{app_id}/pipelines", primary_keys=("app_id", "id"), parent="applications", paginated=True
    ),
}

AUTH_ERROR = "Humanitec rejected the API token. Check the token and its expiration date."
PERMISSION_ERROR = "The Humanitec token cannot read this resource. Check the service user's roles in your organization."
ORGANIZATION_ERROR = (
    "Humanitec could not find the organization. Check the organization ID and the service user's access."
)
INVALID_ORGANIZATION_ERROR = "Enter a Humanitec organization ID with lowercase letters, numbers, and single hyphens."
