from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import quote

from requests import HTTPError, Request, Response

from products.warehouse_sources.sources.revolut_merchant.settings import BASE_URLS, CREATED_DATE_PAGE_SIZE, ENDPOINTS
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    BearerTokenAuth,
    ClientConfig,
    EndpointResource,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    frozen,
    rename_parent_fields,
    rest_api_resource,
    rest_api_resources,
    schema_for_resource,
)

AUTH_ERROR = (
    "Revolut Merchant rejected the Secret API key. Check that it is valid and matches the selected environment."
)
PERMISSION_ERROR = (
    "Your Secret API key cannot access this Revolut Merchant table. Check your Merchant account permissions."
)
VERSION_ERROR = "Revolut Merchant rejected the request. Check the selected API version and reconnect."
SANDBOX_DISPUTES_ERROR = "Revolut Merchant only provides disputes in the Production environment."


@frozen
class RevolutMerchantResumeConfig:
    paginator_state: dict[str, Any]


class CreatedDatePaginator(BasePaginator):
    """Pages by `from_created_date` or `to_created_date`, picked from the order of the first full page.

    The API does not document the sort order, and both bounds include the boundary timestamp. The next
    page repeats the rows at the boundary, so the paginator drops the IDs it already returned there.
    """

    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit
        self._param: str | None = None
        self._value: str | None = None
        self._boundary_ids: set[str] = set()

    def init_request(self, request: Request) -> None:
        self.update_request(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        rows = data if data is not None else []
        full_page = len(rows) >= self.limit
        bound = _parse_created_at_value(self._value) if self._value is not None else None
        # The client yields this same list after update_state, so filtering in place drops the repeats.
        rows[:] = [
            row for row in rows if not (_parse_created_at(row) == bound and str(row.get("id")) in self._boundary_ids)
        ]
        if not full_page:
            self._has_next_page = False
            return
        if not rows:
            raise ValueError("Revolut Merchant returned only rows from the previous page.")
        first = _parse_created_at(rows[0])
        last = _parse_created_at(rows[-1])
        if first == last and self._param is None:
            raise ValueError("Revolut Merchant returned a full page with one created date.")
        param = self._param if first == last else ("to_created_date" if first > last else "from_created_date")
        if self._param is not None and param != self._param:
            raise ValueError("Revolut Merchant changed the sort order between pages.")
        if bound is not None and (last >= bound if param == "to_created_date" else last <= bound):
            raise ValueError("Revolut Merchant created date pagination is not advancing.")
        self._param = param
        self._value = last.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self._boundary_ids = {str(row.get("id")) for row in rows if _parse_created_at(row) == last}
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if self._param is not None and self._value is not None:
            if request.params is None:
                request.params = {}
            request.params[self._param] = self._value

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._param is not None and self._value is not None:
            return {"param": self._param, "value": self._value, "boundary_ids": sorted(self._boundary_ids)}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        if state.get("param") in ("from_created_date", "to_created_date") and state.get("value"):
            self._param = state["param"]
            self._value = state["value"]
            self._boundary_ids = set(state.get("boundary_ids") or [])
            self._has_next_page = True


def _parse_created_at(row: dict[str, Any]) -> datetime:
    return _parse_created_at_value(row["created_at"])


def _parse_created_at_value(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def client_config(api_key: str, environment: str, api_version: str) -> ClientConfig:
    if environment not in BASE_URLS:
        raise ValueError("Select Production or Sandbox for the Revolut Merchant environment.")
    return {
        "base_url": BASE_URLS[environment],
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Revolut-Api-Version": api_version, "Accept": "application/json"},
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": 30,
    }


def get_resource(name: str) -> EndpointResource:
    endpoint = schema_for_resource(ENDPOINTS, name)
    resource: EndpointResource = {
        "name": name,
        "table_name": name,
        "table_format": "delta",
        "write_disposition": "replace",
        "endpoint": endpoint.endpoint,
    }
    if endpoint.created_date_pagination:
        resource["endpoint"] = {**endpoint.endpoint, "paginator": CreatedDatePaginator(CREATED_DATE_PAGE_SIZE)}
    if endpoint.parent and endpoint.parent_id_column:
        resource["include_from_parent"] = ["id"]
        resource["data_map"] = rename_parent_fields(endpoint.parent, {"id": endpoint.parent_id_column})
    return resource


def revolut_merchant_source(
    api_key: str,
    environment: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[RevolutMerchantResumeConfig],
) -> SourceResponse:
    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    resources: list[str | EndpointResource] = [get_resource(endpoint)]
    if endpoint_config.parent:
        resources.insert(0, get_resource(endpoint_config.parent))
    config: RESTAPIConfig = {
        "client": client_config(api_key, environment, api_version),
        "resources": resources,
    }

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(RevolutMerchantResumeConfig(paginator_state=state))

    if endpoint_config.parent:
        resource = rest_api_resources(
            config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        )[-1]
    else:
        resource = rest_api_resource(
            config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        column_hints=resource.column_hints,
        partition_mode="datetime",
        partition_keys=[endpoint_config.partition_key],
        partition_format="month",
        sort_mode=endpoint_config.sort_mode,
    )


def validate_credentials(
    api_key: str, environment: str, api_version: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    if not api_key or any(not 33 <= ord(char) <= 126 for char in api_key):
        return False, "Enter a Revolut Merchant Secret API key without spaces or unsupported characters."
    if schema_name == "disputes" and environment == "sandbox":
        return False, SANDBOX_DISPUTES_ERROR
    selected_endpoint = schema_for_resource(ENDPOINTS, schema_name or "customers")
    endpoint = ENDPOINTS[selected_endpoint.parent] if selected_endpoint.parent else selected_endpoint
    path = endpoint.endpoint.get("path")
    if path is None:
        raise ValueError("Revolut Merchant endpoint is missing a path.")
    config = client_config(api_key, environment, api_version)
    client = RESTClient(
        base_url=config["base_url"],
        auth=BearerTokenAuth(api_key),
        headers=config["headers"],
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=15,
    )
    try:
        page = next(
            client.paginate(
                path=path,
                params={"limit": 1},
                paginator=SinglePagePaginator(),
                data_selector=endpoint.endpoint["data_selector"],
                data_selector_required=True,
            )
        )
        if selected_endpoint.parent and page:
            child = selected_endpoint.endpoint
            child_params = child.get("params") or {}
            resolve_param = next(
                name
                for name, value in child_params.items()
                if isinstance(value, dict) and value.get("type") == "resolve"
            )
            next(
                client.paginate(
                    path=str(child.get("path")).format(**{resolve_param: quote(str(page[0]["id"]), safe="")}),
                    params={"limit": 1} if "limit" in child_params else None,
                    paginator=SinglePagePaginator(),
                    data_selector=child.get("data_selector"),
                    data_selector_required=True,
                )
            )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            return (True, None) if schema_name is None else (False, PERMISSION_ERROR)
        if status == 400:
            return False, VERSION_ERROR
        raise
    return True, None
