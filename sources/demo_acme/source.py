"""DemoAcme: an invented REST source that shows a warehouse source plugin added as one directory.

DEMO (warehouse source plugins): no real vendor sits behind `api.example.com`. The source imports
shared code only from `sources.sdk`, keeps its generated config in `_config.py`, and needs no line
in `_load_all.py`, `generated_configs/` or the `ExternalDataSourceType` enum.
"""

import dataclasses
from typing import Any, Optional, cast

from sources.demo_acme._config import DemoAcmeSourceConfig
from sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    EndpointResource,
    FieldType,
    IncrementalField,
    PageNumberPaginator,
    ReleaseStatus,
    Resource,
    RESTAPIConfig,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceKey,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    make_tracked_session,
    rest_api_resource,
    source_key,
)

SOURCE_KEY = "DemoAcme"
BASE_URL = "https://api.example.com/v1"
ENDPOINTS = ("Widgets", "Orders")
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
_PER_PAGE = 100
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Widgets": {
        "description": "A widget in the invented DemoAcme catalog.",
        "columns": {"id": "Unique identifier for the widget."},
    },
    "Orders": {
        "description": "An order for DemoAcme widgets.",
        "columns": {"id": "Unique identifier for the order."},
    },
}


@dataclasses.dataclass(frozen=False)
class DemoAcmeResumeConfig:
    next_page: int


def _resource(name: str) -> EndpointResource:
    path = name.lower()
    return {
        "name": name,
        "table_name": path,
        "write_disposition": "replace",
        "endpoint": {"data_selector": "data", "path": f"/{path}", "params": {"per_page": _PER_PAGE}},
        "table_format": "delta",
    }


def demo_acme_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DemoAcmeResumeConfig],
) -> Resource:
    session = make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}"}, redact_values=(api_key,), allow_redirects=False
    )

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(DemoAcmeResumeConfig(next_page=int(state["page"])))

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "session": session,
            "paginator": PageNumberPaginator(base_page=1, page=1, page_param="page", total_path=None),
        },
        "resources": [_resource(endpoint)],
    }

    return rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


@SourceRegistry.register
class DemoAcmeSource(ResumableSource[DemoAcmeSourceConfig, DemoAcmeResumeConfig]):
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DemoAcmeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: DemoAcmeSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        session = make_tracked_session(
            headers={"Authorization": f"Bearer {config.api_key}"},
            redact_values=(config.api_key,),
            allow_redirects=False,
        )
        if session.get(f"{BASE_URL}/widgets?per_page=1", timeout=(5, 10)).status_code == 200:
            return True, None
        return False, "Invalid API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DemoAcmeResumeConfig]:
        return ResumableSourceManager[DemoAcmeResumeConfig](inputs, DemoAcmeResumeConfig)

    def source_for_pipeline(
        self,
        config: DemoAcmeSourceConfig,
        resumable_source_manager: ResumableSourceManager[DemoAcmeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        resource = demo_acme_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
        return SourceResponse(name=resource.name, items=lambda: resource, primary_keys=["id"])

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Demo Acme",
            caption="An invented source that shows a warehouse source plugin. It has no real vendor.",
            # The plugin ships `icon.png` next to this file. Serving it from here is layer 3, so the
            # tile points at an icon that frontend/public already serves.
            iconPath="/static/services/billomat.png",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
