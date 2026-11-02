from collections.abc import Generator
from datetime import UTC, date, datetime
from typing import Any, cast
from urllib.parse import quote

from requests import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.yotpo.settings import (
    BASE_URL,
    ENDPOINTS,
    REQUEST_TIMEOUT,
)


class YotpoAuthenticationError(Exception):
    pass


@frozen
class YotpoResumeConfig:
    page: int
    until: str | None = None


def validate_start_date(value: str) -> None:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value or parsed > datetime.now(UTC).date():
        raise ValueError("Enter a start date in YYYY-MM-DD format that is not in the future.")


def get_access_token(app_key: str, api_secret: str) -> str:
    # JSON is required by Yotpo; the framework OAuth helper sends form data.
    with make_tracked_session(redact_values=(api_secret,), capture=False) as session:
        client = RESTClient(
            base_url=BASE_URL,
            session=session,
            allowed_hosts=[],
            allow_redirects=False,
            request_timeout=REQUEST_TIMEOUT,
            retry_budget_seconds=120,
            retry_after_max_seconds=60,
        )
        pages = cast(
            "Generator[list[Any]]",
            client.paginate(
                path="oauth/token",
                method="POST",
                json={"client_id": app_key, "client_secret": api_secret, "grant_type": "client_credentials"},
                paginator=SinglePagePaginator(),
                data_selector="$",
            ),
        )
        try:
            rows = next(pages, [])
            payload = rows[0] if rows else None
        except HTTPError as error:
            if error.response is not None and error.response.status_code in (400, 401, 403):
                raise YotpoAuthenticationError("Yotpo rejected the app key or API secret.") from None
            raise
        finally:
            pages.close()
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise YotpoAuthenticationError("Yotpo did not return an access token.")
    return token


def get_endpoint(endpoint: str, app_key: str, token: str, start_date: str, until: str) -> Endpoint:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    params: dict[str, Any] = dict(settings.params)
    if settings.page_size_param:
        params[settings.page_size_param] = 100
    if settings.email_date_range:
        validate_start_date(start_date)
        params.update(since=start_date, until=until)
    if settings.token_query_param:
        params[settings.token_query_param] = token
    return {
        "path": settings.path.format(app_key=quote(app_key, safe="")),
        "data_selector": settings.data_selector,
        "data_selector_required": True,
        "params": params,
        "paginator": PageNumberPaginator(base_page=1) if settings.page_size_param else "single_page",
    }


def validate_credentials(app_key: str, api_secret: str, start_date: str, schema_name: str | None) -> None:
    endpoint = schema_name or "reviews"
    schema_for_resource(ENDPOINTS, endpoint)
    token = get_access_token(app_key, api_secret)
    probe = get_endpoint(endpoint, app_key, token, start_date, datetime.now(UTC).date().isoformat())
    size_param = ENDPOINTS[endpoint].page_size_param
    params = probe["params"]
    if size_param and params is not None:
        params[size_param] = 1
    resource = rest_api_resource(
        {
            "client": {
                "base_url": BASE_URL,
                "auth": {"type": "api_key", "name": "X-Yotpo-Token", "api_key": token, "location": "header"},
                "allowed_hosts": [],
                "allow_redirects": False,
                "request_timeout": REQUEST_TIMEOUT,
                "retry_budget_seconds": 60,
                "retry_after_max_seconds": 30,
            },
            "resources": [{"name": endpoint, "endpoint": {**probe, "paginator": "single_page"}}],
        },
        team_id=0,
        job_id="credential-validation",
        db_incremental_field_last_value=None,
    )
    list(resource)


def yotpo_source(
    app_key: str,
    api_secret: str,
    start_date: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[YotpoResumeConfig],
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    until = resume.until if resume and resume.until else datetime.now(UTC).date().isoformat()
    token = get_access_token(app_key, api_secret)
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "name": "X-Yotpo-Token", "api_key": token, "location": "header"},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": REQUEST_TIMEOUT,
            "retry_budget_seconds": 120,
            "retry_after_max_seconds": 60,
        },
        "resources": [
            {
                "name": endpoint,
                "write_disposition": "replace",
                "endpoint": get_endpoint(endpoint, app_key, token, start_date, until),
            }
        ],
    }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(YotpoResumeConfig(page=int(state["page"]), until=until))

    resource = rest_api_resource(
        config,
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"page": resume.page} if resume else None,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(settings.primary_keys) if settings.primary_keys else None,
        partition_keys=[settings.partition_key] if settings.partition_key else None,
        partition_mode="datetime" if settings.partition_key else None,
        partition_format="month" if settings.partition_key else None,
        sort_mode=None,
        supports_resume=settings.page_size_param is not None,
    )
