import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_api_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import RESTAPIConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftdefendercloudapps import (
    MicrosoftDefenderCloudAppsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_defender_cloud_apps.settings import (
    ENDPOINTS,
    PAGE_SIZE,
    PRIMARY_KEYS,
)


@frozen
class DefenderResumeConfig:
    offset: int
    since: int | None
    until: int | None


class DefenderPaginator(OffsetPaginator):
    def __init__(self) -> None:
        super().__init__(limit=PAGE_SIZE, offset_param="skip", total_path=None, param_location="json")

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("hasNext"), bool):
            raise ValueError("Microsoft Defender returned a page without a valid hasNext value.")
        self._has_next_page = body["hasNext"]
        if self._has_next_page:
            if not data:
                raise ValueError("Microsoft Defender returned an empty page with more data available.")
            # The total is approximate, and a page can contain fewer rows than the requested limit.
            self.offset += len(data)


class DefenderClient:
    @staticmethod
    def normalize_portal_url(portal_url: str) -> str:
        parsed = urlsplit(portal_url.strip())
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/", "/api", "/api/")
            or not re.fullmatch(r"[a-zA-Z0-9.-]+", parsed.hostname)
        ):
            raise ValueError("Enter the HTTPS portal URL from Settings > Cloud Apps > System > About.")
        return f"https://{parsed.hostname}"

    def __init__(self, config: MicrosoftDefenderCloudAppsSourceConfig, team_id: int, api_version: str) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (  # noqa: PLC0415 -- keeps Django models off the config import path
            ValidateDatabaseHostMixin,
        )

        self.portal_url = self.normalize_portal_url(config.portal_url)
        hostname = urlsplit(self.portal_url).hostname
        assert hostname is not None
        valid, error = ValidateDatabaseHostMixin().is_database_host_valid(hostname, team_id)
        if not valid:
            raise ValueError(error or "Enter a public Microsoft Defender portal URL.")
        self.base_url = f"{self.portal_url}/api/{api_version}/"
        self.auth = APIKeyAuth(api_key=f"Token {config.api_token}")

    def validate_credentials(self, endpoint: str) -> None:
        if endpoint not in ENDPOINTS:
            raise ValueError(f"Unsupported Microsoft Defender table: {endpoint}")
        client = RESTClient(
            base_url=self.base_url,
            auth=self.auth,
            allowed_hosts=[],
            allow_redirects=False,
            request_timeout=(10, 60),
        )
        list(
            client.paginate(
                path=f"{endpoint}/",
                method="POST",
                json={"limit": 1, "skip": 0},
                paginator=SinglePagePaginator(),
                data_selector="data",
                data_selector_required=True,
            )
        )

    def source_response(
        self, inputs: SourceInputs, manager: ResumableSourceManager[DefenderResumeConfig]
    ) -> SourceResponse:
        endpoint = inputs.schema_name
        if endpoint not in ENDPOINTS:
            raise ValueError(f"Unsupported Microsoft Defender table: {endpoint}")
        if inputs.should_use_incremental_field and (endpoint != "alerts" or inputs.incremental_field != "timestamp"):
            raise ValueError("Only the alert timestamp supports incremental imports.")

        since = None
        until = int(datetime.now(UTC).timestamp() * 1000) if endpoint == "alerts" else None
        if inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
            since = int(inputs.db_incremental_field_last_value)

        resume = manager.load_state() if manager.can_resume() else None
        if resume is not None:
            since, until = resume.since, resume.until

        body: dict[str, Any] = {"filters": {}}
        if endpoint == "alerts":
            body.update({"sortField": "date", "sortDirection": "asc"})
            body["filters"] = {"date": {"lte": until}}
            if since is not None:
                body["filters"]["date"]["gte"] = since
        elif endpoint == "entities":
            body.update({"sortField": "date", "sortDirection": "asc"})

        def save_checkpoint(state: dict[str, Any] | None) -> None:
            if state is not None:
                manager.save_state(DefenderResumeConfig(offset=int(state["offset"]), since=since, until=until))

        config: RESTAPIConfig = {
            "client": {
                "base_url": self.base_url,
                "auth": self.auth,
                "paginator": DefenderPaginator(),
                "allowed_hosts": [],
                "allow_redirects": False,
                "request_timeout": (10, 60),
            },
            "resources": [
                {
                    "name": endpoint,
                    "table_format": "delta",
                    "endpoint": {
                        "path": f"{endpoint}/",
                        "method": "POST",
                        "json": body,
                        "data_selector": "data",
                        "data_selector_required": True,
                    },
                }
            ],
        }
        resource = rest_api_resource(
            config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state={"offset": resume.offset} if resume is not None else None,
        )
        return SourceResponse(
            name=endpoint,
            items=lambda: resource,
            primary_keys=PRIMARY_KEYS[endpoint],
            sort_mode="asc" if endpoint == "alerts" else None,
        )
