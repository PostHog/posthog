from collections.abc import Iterable
from typing import Any, Optional, cast

from requests import Request, Response
from requests.exceptions import RequestException

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fillout.settings import (
    ALLOWED_FILLOUT_API_BASE_URLS,
    DEFAULT_FILLOUT_API_BASE_URL,
    FILLOUT_ENDPOINTS,
    FilloutEndpointConfig,
)


def _normalize_api_base_url(api_base_url: str | None) -> str:
    return (api_base_url or DEFAULT_FILLOUT_API_BASE_URL).rstrip("/")


def _validated_api_base_url(api_base_url: str | None) -> str:
    normalized_url = _normalize_api_base_url(api_base_url)
    if normalized_url not in ALLOWED_FILLOUT_API_BASE_URLS:
        raise ValueError(
            "API base URL must be one of https://api.fillout.com/v1/api or https://eu-api.fillout.com/v1/api."
        )
    return normalized_url


def _format_fillout_datetime(value: Any) -> str:
    """Format the incremental watermark for Fillout's `afterDate` filter.

    Truncates to whole seconds, which rounds the lower bound *down* — so a sync
    re-fetches at most a few boundary rows (the merge dedupes them) rather than
    skipping any.
    """
    normalized_value = coerce_datetime_to_utc(value)
    if normalized_value is None:
        return str(value)
    return normalized_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fillout_incremental_window(cursor_path: str) -> IncrementalConfig:
    # `afterDate` is a genuine server-side filter on submission time, and Fillout reports the
    # filtered count in `totalResponses`, so the offset walk terminates at the watermark.
    return {
        "cursor_path": cursor_path,
        "start_param": "afterDate",
        "initial_value": "1970-01-01T00:00:00Z",
        "convert": _format_fillout_datetime,
    }


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _rest_api_client_config(base_api_url: str, api_key: str) -> ClientConfig:
    return {
        "base_url": base_api_url,
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
    }


class FilloutSubmissionsPaginator(OffsetPaginator):
    """Limit/offset paginator for `/forms/{formId}/submissions`.

    Pins `sort=asc` (oldest-first, matching the ascending incremental watermark) and
    `status=finished` (Fillout's default; we don't want in-progress drafts). `totalResponses`
    reflects the `afterDate`-filtered count, so the walk stops at the watermark on incremental
    syncs rather than re-reading each form's full history.
    """

    def __init__(self, limit: int) -> None:
        super().__init__(
            limit=limit,
            total_path="totalResponses",
            offset_param="offset",
            limit_param="limit",
        )

    def init_request(self, request: Request) -> None:
        super().init_request(request)
        request.params.setdefault("sort", "asc")
        request.params.setdefault("status", "finished")


def validate_credentials(
    api_key: str, api_base_url: str | None = None, schema_name: str | None = None
) -> tuple[bool, str | None]:
    try:
        base_url = _validated_api_base_url(api_base_url)
    except ValueError as exc:
        return False, str(exc)

    headers = _auth_headers(api_key)
    errors: list[str] = []

    skip_submissions_validation = schema_name == "forms"

    def _parse_error_description(response: Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                for key in ("message", "error", "description"):
                    value = payload.get(key)
                    if isinstance(value, str) and value:
                        return value
        except Exception:
            pass
        return response.text

    forms_response: Response | None = None
    try:
        forms_response = make_tracked_session().get(f"{base_url}/forms", headers=headers, timeout=10)
        if forms_response.status_code == 401:
            errors.append("Invalid Fillout API key")
        elif forms_response.status_code == 403:
            errors.append("Fillout API key is missing permission to list forms")
        elif forms_response.status_code != 200:
            errors.append(f"/forms endpoint failed: {_parse_error_description(forms_response)}")
    except RequestException as exc:
        errors.append(f"/forms request failed: {exc}")

    if not skip_submissions_validation and forms_response and forms_response.status_code == 200:
        forms_items = forms_response.json()

        # With no forms there's nothing to probe submissions against; that shouldn't block validation.
        if isinstance(forms_items, list) and forms_items:
            first_form = forms_items[0]
            form_id = first_form.get("formId") if isinstance(first_form, dict) else None
            if not isinstance(form_id, str) or not form_id:
                errors.append("Fillout returned an invalid form id while validating submissions access.")
            else:
                try:
                    submissions_response = make_tracked_session().get(
                        f"{base_url}/forms/{form_id}/submissions",
                        headers=headers,
                        params={"limit": 1},
                        timeout=10,
                    )
                    if submissions_response.status_code == 401:
                        errors.append("Invalid Fillout API key")
                    elif submissions_response.status_code == 403:
                        errors.append("Fillout API key is missing permission to read submissions")
                    elif submissions_response.status_code != 200:
                        errors.append(f"/submissions endpoint failed: {_parse_error_description(submissions_response)}")
                except RequestException as exc:
                    errors.append(f"/submissions request failed: {exc}")

    if errors:
        return False, "; ".join(errors)
    return True, None


def get_resource(endpoint: str) -> EndpointResource:
    config = FILLOUT_ENDPOINTS[endpoint]
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": {},
        # `/forms` returns a bare JSON array, so select the root.
        "data_selector": "$",
        "paginator": SinglePagePaginator(),
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _make_source_response(endpoint_config: FilloutEndpointConfig, items_fn) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_key
        if isinstance(endpoint_config.primary_key, list)
        else [endpoint_config.primary_key],
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def fillout_source(
    api_key: str,
    api_base_url: str | None,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = FILLOUT_ENDPOINTS[endpoint]
    base_api_url = _validated_api_base_url(api_base_url)

    if endpoint_config.fanout:
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=FILLOUT_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=endpoint_config.fanout,
                client_config=_rest_api_client_config(base_api_url, api_key),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
                incremental_config_factory=_fillout_incremental_window,
                page_size_param="limit",
                parent_endpoint_extra={
                    "paginator": SinglePagePaginator(),
                    "data_selector": "$",
                },
                child_endpoint_extra={
                    "paginator": FilloutSubmissionsPaginator(limit=endpoint_config.page_size),
                    "data_selector": "responses",
                },
            ),
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    config: RESTAPIConfig = {
        "client": _rest_api_client_config(base_api_url, api_key),
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(endpoint=endpoint)],
    }

    resource = rest_api_resource(config, team_id, job_id, db_incremental_field_last_value)
    return _make_source_response(endpoint_config, lambda: resource)
