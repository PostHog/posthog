import re
from typing import Any

from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.kisi.settings import (
    BASE_URL,
    ENDPOINTS,
    MAX_OFFSET,
    OFFSET_ERROR,
    PAGE_SIZE,
    PARTITION_KEYS,
    PRIMARY_KEYS,
)


@frozen
class KisiResumeConfig:
    offset: int


class KisiPaginator(OffsetPaginator):
    def __init__(self) -> None:
        super().__init__(limit=PAGE_SIZE, total_path=None)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        super().update_state(response, data)
        # Kisi puts the total inside a range header, rather than a separate count header.
        collection_range = re.fullmatch(r"\d+-\d+/(\d+)", response.headers.get("X-Collection-Range", ""))
        if collection_range and data:
            self._has_next_page = self.offset < int(collection_range[1])
        if self.has_next_page and self.offset > MAX_OFFSET:
            raise ValueError(OFFSET_ERROR)


def kisi_auth(api_key: str) -> APIKeyAuth:
    return APIKeyAuth(api_key=f"KISI-LOGIN {api_key}", name="Authorization", location="header")


def validate_credentials(api_key: str) -> None:
    with make_tracked_session() as session:
        response = session.get(
            f"{BASE_URL}/user",
            auth=kisi_auth(api_key),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=(10, 30),
            allow_redirects=False,
        )
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("Kisi returned an unexpected response. Try again later.")


def kisi_source(
    api_key: str,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[KisiResumeConfig],
) -> SourceResponse:
    if inputs.schema_name not in ENDPOINTS:
        raise ValueError(f"Unsupported Kisi table: {inputs.schema_name}")

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(KisiResumeConfig(offset=int(state["offset"])))

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": kisi_auth(api_key),
            "headers": {"Accept": "application/json", "Content-Type": "application/json"},
            "paginator": KisiPaginator(),
            "request_timeout": (10, 30),
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": inputs.schema_name,
                "endpoint": {"path": inputs.schema_name, "data_selector": "$"},
                "write_disposition": "replace",
            }
        ],
    }
    resource = rest_api_resource(
        config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"offset": resume.offset} if resume else None,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS,
        partition_keys=PARTITION_KEYS,
        partition_mode="datetime",
        partition_format="month",
        sort_mode=None,
    )
