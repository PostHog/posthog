from datetime import UTC, datetime
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
    PARTITION_KEYS,
    PRIMARY_KEYS,
    REGION_ERROR,
    REGIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.frontegg import (
    FronteggSourceConfig,
)


@frozen
class FronteggResumeConfig:
    page: int | None = None
    offset: int | None = None
    created_from: str | None = None


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


def _created_from(value: Any) -> str:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    return str(value)


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
    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None and resume.offset is not None:
        # The offset counts rows within the window of the attempt that saved it.
        created_from = resume.created_from
    elif inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
        created_from = _created_from(inputs.db_incremental_field_last_value)
    else:
        created_from = None
    if created_from is not None:
        endpoint["params"] = {**(endpoint.get("params") or {}), "created_from": created_from}
    rest_config: RESTAPIConfig = {
        "client": {"base_url": REGIONS[config.region], "auth": auth, "request_timeout": (10, 60)},
        "resources": [{"name": inputs.schema_name, "endpoint": endpoint}],
    }
    initial_state = (
        {key: value for key, value in (("page", resume.page), ("offset", resume.offset)) if value is not None}
        if resume
        else None
    )

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(
                FronteggResumeConfig(
                    page=int(state["page"]) if "page" in state else None,
                    offset=int(state["offset"]) if "offset" in state else None,
                    created_from=created_from,
                )
            )

    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state or None,
    )
    partition_key = PARTITION_KEYS.get(inputs.schema_name)
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS.get(inputs.schema_name, ["id"]),
        partition_mode="datetime" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )
