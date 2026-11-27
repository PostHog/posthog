from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from requests.exceptions import HTTPError, RequestException
from urllib3.util.retry import Retry

from products.warehouse_sources.sources.sdk import (
    BearerTokenAuth,
    ClientConfig,
    Endpoint,
    JSONResponsePaginator,
    RESTAPIConfig,
    RESTClient,
    RESTClientNonRetryableError,
    RESTClientRetryableError,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceInputs,
    SourceResponse,
    build_dependent_resource,
    frozen,
    make_tracked_session,
    rest_api_resource,
)
from products.warehouse_sources.sources.smartlook._config import SmartlookSourceConfig
from products.warehouse_sources.sources.smartlook.settings import ENDPOINTS, VISITOR_WINDOW_DAYS, SmartlookEndpoint

REGION_URLS = {"eu": "https://api.eu.smartlook.cloud", "us": "https://api.us.smartlook.cloud"}
FUNNEL_STEP_VISITORS = "funnel_step_visitors"


@frozen
class SmartlookResumeConfig:
    paginator_state: dict[str, Any]


def client_config(config: SmartlookSourceConfig) -> ClientConfig:
    if config.region not in REGION_URLS:
        raise ValueError("Select the EU or US region from your Smartlook project settings.")
    return {
        "base_url": REGION_URLS[config.region],
        "auth": {"type": "bearer", "token": config.api_token},
        "headers": {"Accept": "application/json"},
        "paginator": {"type": "json_response", "next_url_path": "_links.nextPage"},
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": (10, 30),
        "retry_budget_seconds": 180,
        "retry_after_max_seconds": 60,
    }


def validate_credentials(config: SmartlookSourceConfig) -> tuple[bool, str | None]:
    connection = client_config(config)
    client = RESTClient(
        base_url=connection["base_url"],
        auth=BearerTokenAuth(token=config.api_token),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=(10, 15),
        max_retry_attempts=1,
        session=make_tracked_session(retry=Retry(total=0), redact_values=(config.api_token,)),
    )
    try:
        next(client.paginate("/api/v1/me", paginator=SinglePagePaginator(), data_selector="$"))
        return True, None
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, "Smartlook rejected the API token. Create a new token in your project settings."
        if status == 403:
            return False, "Smartlook denied API access. Check the token, project region, and REST API access."
        return False, "Smartlook could not validate the token. Try again later."
    except RESTClientRetryableError:
        return False, "Smartlook is unavailable or reached its API request limit. Try again later."
    except RESTClientNonRetryableError:
        return False, "Smartlook returned an invalid response. Check the project region and try again."
    except RequestException:
        return False, "Could not connect to Smartlook. Check the project region and try again."


def visitor_window() -> dict[str, str]:
    end = datetime.now(UTC).date()
    return {"dateFrom": (end - timedelta(days=VISITOR_WINDOW_DAYS)).isoformat(), "dateTo": end.isoformat()}


def endpoint_config(endpoint: SmartlookEndpoint, api_version: str) -> Endpoint:
    result: Endpoint = {
        "path": endpoint.path.replace("{api_version}", api_version),
        "method": endpoint.method,
        "data_selector": endpoint.data_selector,
        "data_selector_required": endpoint.rows_required,
    }
    if endpoint.method == "POST":
        assert endpoint.sort_field is not None
        result["json"] = {"filters": [], "sort": {endpoint.sort_field: "asc"}}
    return result


def _rest_client(config: SmartlookSourceConfig) -> RESTClient:
    connection = client_config(config)
    return RESTClient(
        base_url=connection["base_url"],
        headers=connection["headers"],
        auth=BearerTokenAuth(token=config.api_token),
        paginator=JSONResponsePaginator(next_url_path="_links.nextPage"),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=connection["request_timeout"],
        retry_budget_seconds=connection["retry_budget_seconds"],
        retry_after_max_seconds=connection["retry_after_max_seconds"],
    )


def _step_visitor_ids(client: RESTClient, path: str, params: dict[str, Any]) -> list[str]:
    page = next(client.paginate(path, params=params, paginator=SinglePagePaginator(), data_selector="$"))
    body = page[0] if page else None
    if not isinstance(body, dict) or "totalVisitorsCount" not in body:
        raise ValueError("Smartlook returned an unexpected funnel visitors response.")
    return [visitor for visitor in body.get("visitors") or [] if isinstance(visitor, str)]


def funnel_step_visitor_rows(
    config: SmartlookSourceConfig,
    manager: ResumableSourceManager[SmartlookResumeConfig],
    resume_state: dict[str, Any] | None,
) -> Iterator[list[dict[str, Any]]]:
    # The drop-off endpoint answers one funnel step per request and returns bare visitor ids, so the
    # shared fan-out cannot bind the step or attach the funnel to each row.
    client = _rest_client(config)
    window = visitor_window()
    funnels = ENDPOINTS["funnels"]
    path = ENDPOINTS[FUNNEL_STEP_VISITORS].path
    state = resume_state or {}
    completed: list[str] = list(state.get("completed_funnels") or [])
    resume_funnel = state.get("funnel_id")
    resume_step = int(state.get("next_step") or 0)

    for page in client.paginate(
        funnels.path,
        params={"limit": funnels.page_size},
        data_selector=funnels.data_selector,
        data_selector_required=True,
    ):
        for funnel in page:
            funnel_id = funnel["id"]
            if funnel_id in completed:
                continue
            steps = funnel.get("events") or []
            first_step = resume_step if funnel_id == resume_funnel else 0
            if first_step >= len(steps):
                completed.append(funnel_id)
                manager.save_state(SmartlookResumeConfig(paginator_state={"completed_funnels": list(completed)}))
                manager.safe_point()
                continue
            for step in range(first_step, len(steps)):
                visitor_ids = _step_visitor_ids(
                    client, path.format(funnelId=funnel_id), {**window, "step": step, "success": "true"}
                )
                if step == len(steps) - 1:
                    completed.append(funnel_id)
                    next_state: dict[str, Any] = {"completed_funnels": list(completed)}
                else:
                    next_state = {"completed_funnels": list(completed), "funnel_id": funnel_id, "next_step": step + 1}
                manager.save_state(SmartlookResumeConfig(paginator_state=next_state))
                if not visitor_ids:
                    manager.safe_point()
                    continue
                event = steps[step] if isinstance(steps[step], dict) else {}
                yield [
                    {"funnel_id": funnel_id, "step": step, "event_id": event.get("id"), "visitor_id": visitor_id}
                    for visitor_id in visitor_ids
                ]
        manager.safe_point()


def smartlook_source(
    config: SmartlookSourceConfig,
    manager: ResumableSourceManager[SmartlookResumeConfig],
    inputs: SourceInputs,
    api_version: str,
) -> SourceResponse:
    settings = ENDPOINTS[inputs.schema_name]
    connection = client_config(config)
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(SmartlookResumeConfig(paginator_state=state))

    if settings.name == FUNNEL_STEP_VISITORS:
        resume_state = resume.paginator_state if resume else None
        return SourceResponse(
            name=settings.name,
            items=lambda: funnel_step_visitor_rows(config, manager, resume_state),
            primary_keys=list(settings.primary_keys),
        )

    if settings.fanout is not None:
        resource = build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=settings.name,
            fanout=settings.fanout,
            client_config=connection,
            path_format_values={"api_version": api_version},
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=endpoint_config(ENDPOINTS[settings.fanout.parent_name], api_version),
            child_endpoint_extra=endpoint_config(settings, api_version),
            child_params_extra=visitor_window() if settings.date_window else None,
            page_size_param="limit" if settings.paginated else None,
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        )
    else:
        endpoint = endpoint_config(settings, api_version)
        endpoint["params"] = {"limit": settings.page_size}
        rest_config: RESTAPIConfig = {
            "client": connection,
            "resources": [
                {
                    "name": settings.name,
                    "endpoint": endpoint,
                    "write_disposition": "replace",
                    "table_format": "delta",
                }
            ],
        }
        resource = rest_api_resource(
            rest_config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        )
    return SourceResponse(
        name=settings.name,
        items=lambda: resource,
        primary_keys=list(settings.primary_keys),
        partition_keys=[settings.partition_key] if settings.partition_key else None,
        partition_mode="datetime" if settings.partition_key else None,
        partition_format="month" if settings.partition_key else None,
    )
