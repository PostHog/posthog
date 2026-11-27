from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from requests import Request, Response

from products.warehouse_sources.sources.sage_intacct._config import SageIntacctSourceConfig
from products.warehouse_sources.sources.sage_intacct.settings import (
    BASE_URL,
    PAGE_SIZE,
    QUERY_ROWS_OBJECTS,
    QUERY_ROWS_PAGE_SIZE,
    TOKEN_URL,
)
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    OAuth2Auth,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    frozen,
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


def _model_fields(model: dict[str, Any], prefix: str = "") -> list[str]:
    fields = [
        f"{prefix}{name}"
        for name, spec in (model.get("fields") or {}).items()
        if not (isinstance(spec, dict) and spec.get("writeOnly"))
    ]
    for section in ("groups", "refs"):
        for name, child in (model.get(section) or {}).items():
            if isinstance(child, dict):
                fields.extend(_model_fields(child, f"{prefix}{name}."))
    return fields


def query_fields(client: RESTClient, object_name: str) -> list[str]:
    for models in client.paginate(
        "services/core/model",
        params={"name": object_name},
        paginator=SinglePagePaginator(),
        data_selector='["ia::result"]',
        data_selector_required=True,
    ):
        if len(models) != 1 or not isinstance(models[0], dict):
            raise ValueError("Sage Intacct returned an invalid object model")
        fields = _model_fields(models[0])
        if "key" not in fields:
            raise ValueError("Sage Intacct returned an object model without a key field")
        return fields
    raise ValueError("Sage Intacct returned no object model")


def _nest(row: dict[str, Any]) -> dict[str, Any]:
    # The query service returns dotted field names; nest them so rows match the detail endpoint shape.
    nested: dict[str, Any] = {}
    for path, value in row.items():
        *parents, leaf = path.split(".")
        node = nested
        for part in parents:
            child = node.get(part)
            if not isinstance(child, dict):
                child = node[part] = {}
            node = child
        node[leaf] = value
    return nested


def sage_intacct_rows(
    config: SageIntacctSourceConfig,
    object_name: str,
    manager: ResumableSourceManager[SageIntacctResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    state = manager.load_state() if manager.can_resume() else None
    paginator = SageIntacctPaginator(start=state.next_start if state else 1)
    client = make_client(config)
    next_start: int | None = None
    query_rows = object_name in QUERY_ROWS_OBJECTS

    def page_state_hook(next_state: dict[str, Any] | None, has_next_page: bool) -> None:
        nonlocal next_start
        next_start = next_state["next_start"] if next_state is not None else None

    try:
        fields = query_fields(client, object_name) if query_rows else ["key"]
        for references in client.paginate(
            "services/core/query",
            method="POST",
            json={
                "object": object_name,
                "fields": fields,
                "orderBy": [{"key": "asc"}],
                "size": QUERY_ROWS_PAGE_SIZE if query_rows else PAGE_SIZE,
            },
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
                if query_rows:
                    rows.append(_nest(reference))
                    continue
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
