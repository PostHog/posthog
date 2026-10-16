from typing import Any

from requests import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import OAuth2Auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.frontegg.settings import (
    ENDPOINTS,
    REGION_ERROR,
    REGIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.frontegg import (
    FronteggSourceConfig,
)


@frozen
class FronteggResumeConfig:
    page: int


class FronteggAuth(OAuth2Auth):
    # Frontegg requires JSON credentials, so the standard OAuth form exchange cannot authenticate it.
    def __init__(self, config: FronteggSourceConfig) -> None:
        if config.region not in REGIONS:
            raise ValueError(REGION_ERROR)
        super().__init__(
            token_url=f"{REGIONS[config.region]}/auth/vendor",
            client_id=config.client_id,
            client_secret=config.api_key,
            access_token_name="token",
            expires_in_name="expiresIn",
        )

    def _obtain_token(self, timeout: tuple[float, float] | None = None) -> None:
        assert self.token_url is not None
        with make_tracked_session(capture=False, allow_redirects=False, redact_values=self.secret_values()) as session:
            response = session.post(
                self.token_url,
                json={"clientId": self.client_id, "secret": self.client_secret},
                timeout=timeout or (10, 30),
            )
            response.raise_for_status()
            if response.status_code != 200:
                raise HTTPError("Frontegg returned an unexpected authentication status.", response=response)
            try:
                payload = response.json()
            except ValueError:
                payload = None
            self._apply_token_response(payload if isinstance(payload, dict) else None)


def frontegg_source(
    config: FronteggSourceConfig,
    manager: ResumableSourceManager[FronteggResumeConfig],
    inputs: SourceInputs,
    api_version: str,
) -> SourceResponse:
    if inputs.schema_name not in ENDPOINTS:
        raise ValueError(f"Unsupported Frontegg table: {inputs.schema_name}")
    auth = FronteggAuth(config)
    endpoint = ENDPOINTS[inputs.schema_name].copy()
    path = endpoint["path"]
    if path is None:
        raise ValueError(f"Frontegg table has no endpoint path: {inputs.schema_name}")
    endpoint["path"] = path.format(api_version=api_version)
    rest_config: RESTAPIConfig = {
        "client": {"base_url": REGIONS[config.region], "auth": auth, "request_timeout": (10, 60)},
        "resources": [{"name": inputs.schema_name, "endpoint": endpoint}],
    }
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(FronteggResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"page": resume.page} if resume else None,
    )
    return SourceResponse(name=inputs.schema_name, items=lambda: resource, primary_keys=["id"])
