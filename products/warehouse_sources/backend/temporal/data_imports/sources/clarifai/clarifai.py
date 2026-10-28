import re
from typing import Any, cast
from urllib.parse import urlsplit

from requests import Response
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.clarifai.settings import (
    AUTH_ERROR,
    CLARIFAI_ENDPOINTS,
    DEFAULT_API_HOST,
    HOST_ERROR,
    PERMISSION_ERROR,
    RESOURCE_ERROR,
    ClarifaiEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    PaginatorConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    UNKNOWN_RESOURCE_PREFIX,
    UnknownResourceError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clarifai import (
    ClarifaiSourceConfig,
)


@frozen
class ClarifaiResumeConfig:
    page: int | None = None
    # Fan-out endpoints store the state that `build_dependent_resource` checkpoints per parent.
    fanout_state: dict[str, Any] | None = None


def _add_input_id(row: dict[str, Any]) -> dict[str, Any]:
    input_data = row.get("input")
    row["input_id"] = input_data.get("id") if isinstance(input_data, dict) else None
    return row


ROW_MAPS = {"dataset_inputs": _add_input_id}


class ClarifaiAPIError(ValueError):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(message)


class ClarifaiClient(ValidateDatabaseHostMixin):
    def __init__(self, config: ClarifaiSourceConfig, team_id: int, api_version: str) -> None:
        host = (config.api_host or DEFAULT_API_HOST).strip().rstrip("/")
        try:
            parts = urlsplit(host)
            valid_host = (
                parts.scheme == "https"
                and parts.hostname
                and not parts.username
                and not parts.password
                and not parts.path
                and not parts.query
                and not parts.fragment
                and not any(character.isspace() for character in host)
                and "\\" not in host
                and (parts.port is None or 0 < parts.port <= 65535)
            )
        except ValueError:
            valid_host = False
        if not valid_host:
            raise ValueError(HOST_ERROR)
        host_valid, _ = self.is_database_host_valid(parts.hostname or "", team_id)
        if not host_valid:
            raise ValueError(HOST_ERROR)
        for value in (config.user_id, config.app_id):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
                raise ValueError(
                    "Enter a valid Clarifai user ID and app ID. Use letters, numbers, periods, hyphens, or underscores."
                )
        self.config = config
        self.team_id = team_id
        self.base_url = f"{host}/{api_version}/users/{config.user_id}/apps/{config.app_id}/"

    @staticmethod
    def check_response(response: Response, **kwargs: object) -> Response:
        if not 200 <= response.status_code < 300:
            return response
        try:
            body = response.json()
        except ValueError:
            raise RESTClientRetryableError("Clarifai returned an invalid JSON response.") from None
        status = body.get("status") if isinstance(body, dict) else None
        code = status.get("code") if isinstance(status, dict) else None
        if code in (10000, 10001, 10002):
            return response
        if code in (10030, 11003, 11005):
            raise RESTClientRetryableError("Clarifai is busy or has reached its request limit. Try again later.")
        if code in (11001, 11002, 11008, 11009, 11200):
            raise ClarifaiAPIError(code, AUTH_ERROR)
        if code == 11007:
            raise ClarifaiAPIError(code, PERMISSION_ERROR)
        if code == 11101:
            raise ClarifaiAPIError(code, RESOURCE_ERROR)
        if code in (11000, 11004, 11006):
            raise ClarifaiAPIError(
                code, "Clarifai account access is limited. Check your account plan and usage limits."
            )
        raise ValueError("Clarifai returned an unsuccessful response. Check the API status and try again.")

    def client_config(self, *, probe: bool = False) -> ClientConfig:
        session = make_tracked_session(redact_values=(self.config.personal_access_token,), allow_redirects=False)
        # Clarifai reports API failures in the JSON status, including responses with HTTP 200.
        session.hooks["response"].append(self.check_response)
        return {
            "base_url": self.base_url,
            "auth": {
                "type": "api_key",
                "name": "Authorization",
                "api_key": f"Key {self.config.personal_access_token}",
            },
            "session": session,
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": (10, 60),
            # PageNumberPaginatorConfig and the runtime constructor currently disagree on this field name.
            "paginator": "single_page"
            if probe
            else cast(PaginatorConfig, {"type": "page_number", "base_page": 1, "total_path": None}),
        }

    @staticmethod
    def endpoint_config(endpoint: str) -> ClarifaiEndpointConfig:
        config = CLARIFAI_ENDPOINTS.get(endpoint)
        if config is None:
            raise UnknownResourceError(f"{UNKNOWN_RESOURCE_PREFIX} {endpoint}")
        return config

    def resource_config(self, endpoint: str, *, probe: bool = False) -> RESTAPIConfig:
        config = self.endpoint_config(endpoint)
        if config.fanout is not None:
            if not probe:
                raise ValueError(f"{endpoint} fans out over {config.fanout.parent_name} and has no flat resource.")
            # A child list needs a parent ID, so the probe checks the parent list instead.
            config = self.endpoint_config(config.fanout.parent_name)
        return {
            "client": self.client_config(probe=probe),
            "resources": [
                {
                    "name": config.name,
                    "endpoint": {
                        "path": config.path,
                        "data_selector": config.data_selector,
                        "params": {"page": 1, "per_page": 1 if probe else config.page_size, **config.params},
                    },
                }
            ],
        }

    def own_app_rows(self, row: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        # Listings scoped to an app can also return Clarifai main models, whose children 404 under this app's path.
        if row.get("user_id", self.config.user_id) != self.config.user_id:
            return []
        if row.get("app_id", self.config.app_id) != self.config.app_id:
            return []
        return row

    def source(
        self,
        endpoint: str,
        job_id: str,
        manager: ResumableSourceManager[ClarifaiResumeConfig],
    ) -> SourceResponse:
        config = self.endpoint_config(endpoint)
        resume = manager.load_state() if manager.can_resume() else None

        resource: Resource
        if config.fanout is not None:
            parent = self.endpoint_config(config.fanout.parent_name)

            def save_fanout_state(state: dict[str, Any] | None) -> None:
                if state:
                    manager.save_state(ClarifaiResumeConfig(fanout_state=state))

            resource = cast(
                Resource,
                build_dependent_resource(
                    endpoint_configs=CLARIFAI_ENDPOINTS,
                    child_endpoint=endpoint,
                    fanout=config.fanout,
                    client_config=self.client_config(),
                    path_format_values={},
                    team_id=self.team_id,
                    job_id=job_id,
                    db_incremental_field_last_value=None,
                    page_size_param="per_page",
                    parent_endpoint_extra={"data_selector": parent.data_selector},
                    parent_data_map=self.own_app_rows,
                    child_endpoint_extra={"data_selector": config.data_selector},
                    resume_hook=save_fanout_state,
                    initial_paginator_state=resume.fanout_state if resume else None,
                ),
            )
        else:

            def save_checkpoint(state: dict[str, Any] | None) -> None:
                if state is not None:
                    manager.save_state(ClarifaiResumeConfig(page=int(state["page"])))

            resource = rest_api_resource(
                self.resource_config(endpoint),
                team_id=self.team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                initial_paginator_state={"page": resume.page} if resume and resume.page is not None else None,
                resume_hook=save_checkpoint,
            )
        row_map = ROW_MAPS.get(endpoint)
        if row_map is not None:
            resource.add_map(row_map)
        return SourceResponse(
            name=endpoint,
            items=lambda: resource,
            primary_keys=config.primary_keys,
            sort_mode=None,
            on_complete=manager.clear_state,
        )


def validate_credentials(
    config: ClarifaiSourceConfig, team_id: int, schema_name: str | None, api_version: str
) -> tuple[bool, str | None]:
    try:
        client = ClarifaiClient(config, team_id, api_version)
        resource = rest_api_resource(
            client.resource_config(schema_name or "models", probe=True),
            team_id=team_id,
            job_id="",
            db_incremental_field_last_value=None,
        )
        list(resource)
    except ClarifaiAPIError as error:
        if error.code == 11007 and schema_name is None:
            return True, None
        return False, str(error)
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            return (True, None) if schema_name is None else (False, PERMISSION_ERROR)
        if status == 404:
            return False, RESOURCE_ERROR
        raise
    except ValueError as error:
        return False, str(error)
    return True, None
