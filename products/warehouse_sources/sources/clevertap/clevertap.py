from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

from requests import Request, Response

from products.warehouse_sources.sources.clevertap._config import ClevertapSourceConfig
from products.warehouse_sources.sources.clevertap.settings import (
    CAMPAIGN_REPORT_RESPONSE_ACTIONS,
    CAMPAIGN_WINDOW_DAYS,
    CAMPAIGNS_PATH,
    CONTENT_BLOCK_PAGE_SIZE,
    ENDPOINTS,
    EXCLUDED_EVENTS,
    EXPORT_ENDPOINTS,
    PAGE_SIZE,
    REGIONS,
    REPORT_RESPONSE_ACTIONS,
    RESPONSE_ACTIONS,
)
from products.warehouse_sources.sources.sdk import (
    APIKeyAuth,
    BasePaginator,
    ClientConfig,
    Endpoint,
    EndpointResource,
    PageNumberPaginator,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceInputs,
    SourceResponse,
    create_response_hooks,
    frozen,
    make_tracked_session,
    rest_api_resource,
    schema_for_resource,
)


@frozen
class ClevertapResumeConfig:
    cursor: str | None
    completed: bool = False
    page: int | None = None
    window_from: str | None = None
    campaign_id: int | None = None


class ClevertapPaginator(BasePaginator):
    def __init__(self) -> None:
        super().__init__()
        self._cursor: str | None = None

    def init_request(self, request: Request) -> None:
        if self._cursor is not None:
            self.update_request(request)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        body = response.json()
        if not isinstance(body, dict) or body.get("status") != "success":
            raise ValueError("CleverTap returned an unexpected export response.")
        if response.request.method == "POST":
            cursor = body.get("cursor")
            if not isinstance(cursor, str) or not cursor:
                raise ValueError("CleverTap did not return an export cursor.")
        else:
            records = body.get("records", [])
            if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
                raise ValueError("CleverTap returned an invalid records list.")
            cursor = body.get("next_cursor")
            if cursor is not None and (not isinstance(cursor, str) or not cursor):
                raise ValueError("CleverTap returned an invalid export cursor.")
        self._cursor = cursor
        self._has_next_page = cursor is not None

    def update_request(self, request: Request) -> None:
        request.method = "GET"
        request.json = None
        request.data = None
        request.params = {"cursor": self._cursor}

    def get_resume_state(self) -> dict[str, Any] | None:
        return {"cursor": self._cursor} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        self._cursor = state["cursor"]


def campaign_window_end(start: date, end: date) -> date:
    return min(start + timedelta(days=CAMPAIGN_WINDOW_DAYS - 1), end)


@frozen
class CampaignWindow:
    start: date
    end: date


def campaign_windows(start: date, end: date) -> Iterator[CampaignWindow]:
    while start <= end:
        window_end = campaign_window_end(start, end)
        yield CampaignWindow(start=start, end=window_end)
        start = window_end + timedelta(days=1)


def campaign_window_body(start: date, end: date) -> dict[str, int]:
    return {"from": int(start.strftime("%Y%m%d")), "to": int(end.strftime("%Y%m%d"))}


class CampaignWindowPaginator(BasePaginator):
    def __init__(self, start: date, end: date) -> None:
        super().__init__()
        self._start = start
        self._end = end

    def init_request(self, request: Request) -> None:
        self.update_request(request)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        self._start = campaign_window_end(self._start, self._end) + timedelta(days=1)
        self._has_next_page = self._start <= self._end

    def update_request(self, request: Request) -> None:
        request.json = campaign_window_body(self._start, campaign_window_end(self._start, self._end))

    def get_resume_state(self) -> dict[str, Any] | None:
        return {"from": self._start.isoformat()} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        self._start = date.fromisoformat(state["from"])


class ContentBlockPaginator(PageNumberPaginator):
    def __init__(self) -> None:
        super().__init__(base_page=1, page_param="pageNumber")

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        super().update_state(response, data)
        total = response.json().get("total")
        if self._has_next_page and isinstance(total, int) and (self.page - 1) * CONTENT_BLOCK_PAGE_SIZE >= total:
            self._has_next_page = False


def validate_configuration(config: ClevertapSourceConfig) -> date:
    if config.region not in REGIONS:
        raise ValueError("Select a supported CleverTap region.")
    if not config.event_name.strip():
        raise ValueError("Enter a CleverTap event name.")
    for credential in (config.account_id, config.passcode):
        if not credential or not credential.isascii() or any(character in credential for character in "\r\n"):
            raise ValueError("Enter a valid CleverTap account ID and passcode.")
    try:
        start = datetime.strptime(config.start_date, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Enter the start date in YYYY-MM-DD format.") from None
    if start > datetime.now(UTC).date() - timedelta(days=1):
        raise ValueError("The start date must be before today (UTC).")
    return start


def _yesterday() -> date:
    return datetime.now(UTC).date() - timedelta(days=1)


def _endpoint_config(config: ClevertapSourceConfig, endpoint: str, start: date, *, probe: bool) -> Endpoint:
    end = _yesterday()
    if endpoint in EXPORT_ENDPOINTS:
        if endpoint == "events" and config.event_name in EXCLUDED_EVENTS:
            raise ValueError("CleverTap does not export this notification event. Select another event name.")
        return {
            "path": ENDPOINTS[endpoint].path,
            "method": "POST",
            "params": {"batch_size": 1 if probe else PAGE_SIZE, "app": "true", "events": "true", "profile": "true"},
            "json": {
                "event_name": config.event_name,
                "from": int((end if probe else start).strftime("%Y%m%d")),
                "to": int(end.strftime("%Y%m%d")),
            },
            "data_selector": "$" if probe else "records",
            "paginator": SinglePagePaginator() if probe else ClevertapPaginator(),
            "response_actions": RESPONSE_ACTIONS,
        }
    if endpoint == "message_reports":
        return {
            "path": ENDPOINTS[endpoint].path,
            "method": "POST",
            "json": {"from": start.strftime("%Y%m%d"), "to": end.strftime("%Y%m%d"), "daily": False},
            "data_selector": "messages",
            "paginator": SinglePagePaginator(),
            "response_actions": REPORT_RESPONSE_ACTIONS,
        }
    if endpoint == "campaigns":
        return {
            "path": CAMPAIGNS_PATH,
            "method": "POST",
            "data_selector": "targets",
            "paginator": CampaignWindowPaginator(end if probe else start, end),
            "response_actions": REPORT_RESPONSE_ACTIONS,
        }
    if endpoint == "content_blocks":
        # Full refresh: page-number paging over an updatedFrom filter can skip a block that moves between pages.
        return {
            "path": ENDPOINTS[endpoint].path,
            "params": {"pageSize": 1 if probe else CONTENT_BLOCK_PAGE_SIZE},
            "data_selector": "contentBlocks",
            "paginator": SinglePagePaginator() if probe else ContentBlockPaginator(),
            "response_actions": REPORT_RESPONSE_ACTIONS,
        }
    raise ValueError(f"CleverTap endpoint {endpoint} has no list request.")


def _client_config(config: ClevertapSourceConfig) -> ClientConfig:
    return {
        "base_url": REGIONS[config.region],
        "headers": {"X-CleverTap-Account-Id": config.account_id},
        "auth": {
            "type": "api_key",
            "name": "X-CleverTap-Passcode",
            "api_key": config.passcode,
            "location": "header",
        },
        "session": make_tracked_session(redact_values=(config.account_id, config.passcode)),
        "request_timeout": (10, 60),
        "retry_budget_seconds": 200,
        "retry_after_max_seconds": 60,
        "allow_redirects": False,
    }


def build_rest_config(config: ClevertapSourceConfig, endpoint: str, *, probe: bool = False) -> RESTAPIConfig:
    schema_for_resource(ENDPOINTS, endpoint)
    start = validate_configuration(config)
    resource: EndpointResource = {
        "name": endpoint,
        "table_name": endpoint,
        "table_format": "delta",
        "write_disposition": "replace",
        "endpoint": _endpoint_config(config, endpoint, start, probe=probe),
    }
    return {"client": _client_config(config), "resources": [resource]}


def probe_credentials(config: ClevertapSourceConfig, team_id: int, endpoint: str) -> None:
    # The message report API can allow one request per hour, so report tables probe the campaign list.
    probe_endpoint = endpoint if endpoint in EXPORT_ENDPOINTS or endpoint == "content_blocks" else "campaigns"
    resource = rest_api_resource(
        build_rest_config(config, probe_endpoint, probe=True), team_id, "clevertap-credentials", None
    )
    for page in resource:
        if probe_endpoint not in EXPORT_ENDPOINTS:
            continue
        if len(page) != 1 or page[0].get("status") != "success" or not page[0].get("cursor"):
            raise ValueError("CleverTap did not return an export cursor.")


def _report_client(config: ClevertapSourceConfig) -> RESTClient:
    return RESTClient(
        base_url=REGIONS[config.region],
        headers={"X-CleverTap-Account-Id": config.account_id},
        auth=APIKeyAuth(api_key=config.passcode, name="X-CleverTap-Passcode", location="header"),
        paginator=SinglePagePaginator(),
        session=make_tracked_session(redact_values=(config.account_id, config.passcode)),
        request_timeout=(10, 60),
        retry_budget_seconds=200,
        retry_after_max_seconds=60,
        allow_redirects=False,
    )


def iter_campaign_reports(
    config: ClevertapSourceConfig,
    start: date,
    manager: ResumableSourceManager[ClevertapResumeConfig],
    resume: ClevertapResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    if resume is not None and resume.window_from is not None:
        start = date.fromisoformat(resume.window_from)
    last_done = resume.campaign_id if resume is not None else None
    list_hooks = create_response_hooks(REPORT_RESPONSE_ACTIONS, "campaign_reports")
    report_hooks = create_response_hooks(CAMPAIGN_REPORT_RESPONSE_ACTIONS, "campaign_reports")
    client = _report_client(config)
    try:
        for window in campaign_windows(start, _yesterday()):
            manager.save_state(
                ClevertapResumeConfig(cursor=None, window_from=window.start.isoformat(), campaign_id=last_done)
            )
            campaigns = [
                campaign
                for page in client.paginate(
                    path=CAMPAIGNS_PATH,
                    method="POST",
                    json=campaign_window_body(window.start, window.end),
                    data_selector="targets",
                    hooks=list_hooks,
                )
                for campaign in page
                if isinstance(campaign, dict) and campaign.get("status") == "completed"
            ]
            manager.safe_point()
            ids = [campaign.get("id") for campaign in campaigns]
            if last_done in ids:
                campaigns = campaigns[ids.index(last_done) + 1 :]
            last_done = None
            for campaign in campaigns:
                rows = [
                    {
                        **result,
                        "campaign_id": campaign["id"],
                        "campaign_name": campaign.get("name"),
                        "scheduled_on": campaign.get("scheduled_on"),
                    }
                    for page in client.paginate(
                        path=ENDPOINTS["campaign_reports"].path,
                        method="POST",
                        json={"id": campaign["id"]},
                        data_selector="result",
                        hooks=report_hooks,
                    )
                    for result in page
                    if isinstance(result, dict)
                ]
                manager.save_state(
                    ClevertapResumeConfig(cursor=None, window_from=window.start.isoformat(), campaign_id=campaign["id"])
                )
                if rows:
                    yield rows
                else:
                    manager.safe_point()
    finally:
        client.session.close()


def _paginator_state(resume: ClevertapResumeConfig | None) -> dict[str, Any] | None:
    if resume is None:
        return None
    state = {"cursor": resume.cursor, "page": resume.page, "from": resume.window_from}
    return {key: value for key, value in state.items() if value is not None} or None


def clevertap_source(
    config: ClevertapSourceConfig,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[ClevertapResumeConfig],
) -> SourceResponse:
    endpoint = inputs.schema_name
    definition = schema_for_resource(ENDPOINTS, endpoint)
    partition_key = definition.partition_key
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.completed:
        return SourceResponse(
            name=endpoint, items=lambda: iter(()), primary_keys=list(definition.primary_keys), sort_mode=None
        )

    if endpoint == "campaign_reports":
        start = validate_configuration(config)
        return SourceResponse(
            name=endpoint,
            items=lambda: iter_campaign_reports(config, start, resumable_source_manager, resume),
            primary_keys=list(definition.primary_keys),
            sort_mode=None,
        )

    rest_config = build_rest_config(config, endpoint)

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is None:
            resumable_source_manager.save_state(ClevertapResumeConfig(cursor=None, completed=True))
            return
        resumable_source_manager.save_state(
            ClevertapResumeConfig(cursor=state.get("cursor"), page=state.get("page"), window_from=state.get("from"))
        )

    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=_paginator_state(resume),
    )
    if endpoint == "events":

        def add_event_fields(row: dict[str, Any]) -> dict[str, Any]:
            row["event_name"] = config.event_name
            # CleverTap ts uses account time, so the partition date must not imply UTC.
            row["event_date"] = datetime.strptime(str(row["ts"]), "%Y%m%d%H%M%S").date().isoformat()
            return row

        resource.add_map(add_event_fields)
    elif endpoint == "message_reports":

        def rename_message_id(row: dict[str, Any]) -> dict[str, Any]:
            # CleverTap names this field with a space.
            row["message_id"] = row.pop("message id", None)
            return row

        resource.add_map(rename_message_id)
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(definition.primary_keys),
        partition_keys=[partition_key] if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        sort_mode=None,
    )
