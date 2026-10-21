from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import OAuth2Auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sageintacct import (
    SageIntacctSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.settings import (
    BASE_URL,
    PAGE_SIZE,
    TOKEN_URL,
)


@frozen
class SageIntacctResumeConfig:
    next_start: int


class SageIntacctPaginator(BasePaginator):
    def __init__(self, start: int = 1) -> None:
        super().__init__()
        self.start = start

    def init_request(self, request: Request) -> None:
        self.update_request(request)

    def update_request(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        request.json["start"] = self.start

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("ia::result"), list):
            raise ValueError("Sage Intacct returned an invalid query result")
        metadata = body.get("ia::meta")
        if not isinstance(metadata, dict) or "next" not in metadata:
            raise ValueError("Sage Intacct returned no pagination metadata")
        next_start = metadata["next"]
        if next_start is None:
            self._has_next_page = False
            return
        if isinstance(next_start, bool) or not isinstance(next_start, int) or next_start <= self.start:
            raise ValueError("Sage Intacct pagination did not advance")
        self.start = next_start
        self._has_next_page = True

    def get_resume_state(self) -> dict[str, Any] | None:
        return {"next_start": self.start} if self.has_next_page else None


def make_client(config: SageIntacctSourceConfig) -> RESTClient:
    return RESTClient(
        base_url=BASE_URL,
        auth=OAuth2Auth(
            token_url=TOKEN_URL,
            client_id=config.client_id,
            client_secret=config.client_secret,
            grant_type="client_credentials",
            extra_token_request_params={"username": config.username},
        ),
        allow_redirects=False,
        allowed_hosts=["api.intacct.com"],
    )


def probe_credentials(config: SageIntacctSourceConfig, object_name: str) -> None:
    client = make_client(config)
    try:
        for _ in client.paginate(
            "services/core/query",
            method="POST",
            json={"object": object_name, "fields": ["key"], "start": 1, "size": 1},
            paginator=SageIntacctPaginator(),
            data_selector='["ia::result"]',
            data_selector_required=True,
        ):
            break
    finally:
        client.session.close()


def sage_intacct_rows(
    config: SageIntacctSourceConfig,
    object_name: str,
    manager: ResumableSourceManager[SageIntacctResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    state = manager.load_state() if manager.can_resume() else None
    paginator = SageIntacctPaginator(start=state.next_start if state else 1)
    client = make_client(config)
    next_start: int | None = None

    def page_state_hook(next_state: dict[str, Any] | None, has_next_page: bool) -> None:
        nonlocal next_start
        next_start = next_state["next_start"] if next_state is not None else None

    try:
        for references in client.paginate(
            "services/core/query",
            method="POST",
            json={"object": object_name, "fields": ["key"], "orderBy": [{"key": "asc"}], "size": PAGE_SIZE},
            paginator=paginator,
            data_selector='["ia::result"]',
            data_selector_required=True,
            page_state_hook=page_state_hook,
        ):
            rows: list[dict[str, Any]] = []
            for reference in references:
                key = reference.get("key") if isinstance(reference, dict) else None
                if not isinstance(key, str) or not key:
                    raise ValueError("Sage Intacct returned a record without a key")
                for records in client.paginate(
                    f"objects/{object_name}/{quote(key, safe='')}",
                    paginator=SinglePagePaginator(),
                    data_selector='["ia::result"]',
                    data_selector_required=True,
                ):
                    if len(records) != 1 or not isinstance(records[0], dict) or records[0].get("key") != key:
                        raise ValueError("Sage Intacct returned an invalid record")
                    rows.append(records[0])
            # Save only after every record in this page is ready for the pipeline.
            if next_start is not None:
                manager.save_state(SageIntacctResumeConfig(next_start=next_start))
            yield rows
    finally:
        client.session.close()
