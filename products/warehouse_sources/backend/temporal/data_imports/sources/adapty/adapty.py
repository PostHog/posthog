from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.adapty.settings import (
    ANALYTICS_BASE_URL,
    CHART_IDS,
    ENDPOINTS,
    SERVER_BASE_URL,
    AdaptyEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientNonRetryableError,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adapty import AdaptySourceConfig

REQUEST_TIMEOUT = (10, 30)
RETRY_BUDGET_SECONDS = 180


@frozen
class AdaptyResumeConfig:
    next_date: str | None = None
    end_date: str | None = None
    chart_index: int = 0
    page: int = 1


def report_body(endpoint: AdaptyEndpoint, day: date, chart_id: str | None = None) -> dict[str, Any]:
    body = {**endpoint.body, "filters": {"date": [day.isoformat(), day.isoformat()]}, "format": "json"}
    if chart_id is not None:
        body["chart_id"] = chart_id
    return body


def api_client(api_key: str, *, paywalls: bool = False) -> RESTClient:
    return RESTClient(
        base_url=SERVER_BASE_URL if paywalls else ANALYTICS_BASE_URL,
        auth=APIKeyAuth(api_key=f"Api-Key {api_key}"),
        headers={"Accept": "application/json", "Adapty-Tz": "UTC"},
        paginator=SinglePagePaginator(),
        request_timeout=REQUEST_TIMEOUT,
        retry_budget_seconds=RETRY_BUDGET_SECONDS,
        retry_after_max_seconds=60,
        allowed_hosts=[],
        allow_redirects=False,
    )


def normalize_report(
    endpoint: AdaptyEndpoint, payload: object, day: date, chart_id: str | None
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("Adapty returned an invalid report. Expected a JSON object.")
    if endpoint.shape == "metrics":
        metrics = payload.get("data") if chart_id is not None else payload
        if not isinstance(metrics, dict) or any(not isinstance(value, dict) for value in metrics.values()):
            raise ValueError("Adapty returned an invalid metric report.")
        return [
            {
                **value,
                "date": day.isoformat(),
                "metric": metric,
                **({"chart_id": chart_id} if chart_id is not None else {}),
            }
            for metric, value in metrics.items()
        ]
    if not isinstance(payload.get("data"), list):
        raise ValueError("Adapty returned an invalid report. Expected a data array.")
    # The spec does not define inner time-series fields, so preserve each report's nested data.
    return [{**payload, "date": day.isoformat()}]


def validate_credentials(api_key: str, schema_name: str | None) -> tuple[bool, str | None]:
    endpoint = schema_for_resource(ENDPOINTS, schema_name or "Analytics")
    client = api_client(api_key, paywalls=endpoint.shape == "paywalls")
    try:
        if endpoint.shape == "paywalls":
            list(
                client.paginate(
                    path=endpoint.path,
                    params={"page[number]": 1, "page[size]": 1},
                    data_selector="data",
                    data_selector_required=True,
                )
            )
        else:
            day = datetime.now(UTC).date() - timedelta(days=1)
            chart_id = "revenue" if schema_name in (None, "Analytics") else None
            pages = list(
                client.paginate(
                    path=endpoint.path, method="POST", json=report_body(endpoint, day, chart_id), data_selector="$"
                )
            )
            if len(pages) != 1 or len(pages[0]) != 1:
                raise ValueError("Invalid Adapty report")
            normalize_report(endpoint, pages[0][0], day, chart_id)
        return True, None
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 403 and schema_name is None:
            return True, None
        if status == 401:
            return False, "Adapty rejected the API key. Enter the app's secret API key."
        if status == 403:
            return False, "Adapty denied access to this table. Check the app's API permissions."
        return False, "Adapty rejected the request. Check API access for this app and try again."
    except (RESTClientRetryableError, RESTClientNonRetryableError, ValueError):
        return False, "Could not read Adapty data. Check API access for this app and try again."
    finally:
        client.session.close()


def iter_reports(
    config: AdaptySourceConfig, endpoint: AdaptyEndpoint, manager: ResumableSourceManager[AdaptyResumeConfig]
) -> Iterator[list[dict[str, Any]]]:
    resume = manager.load_state() if manager.can_resume() else None
    day = date.fromisoformat(resume.next_date if resume and resume.next_date else config.start_date)
    end = (
        date.fromisoformat(resume.end_date)
        if resume and resume.end_date
        else datetime.now(UTC).date() - timedelta(days=1)
    )
    chart_index = resume.chart_index if resume else 0
    charts: tuple[str | None, ...] = CHART_IDS if endpoint is ENDPOINTS["Analytics"] else (None,)
    client = api_client(config.api_key)
    try:
        while day <= end:
            for index in range(chart_index, len(charts)):
                manager.safe_point()
                interruptible_wait(0.5, safe_point=manager.safe_point)
                for page in client.paginate(
                    path=endpoint.path, method="POST", json=report_body(endpoint, day, charts[index]), data_selector="$"
                ):
                    if len(page) != 1:
                        raise ValueError("Adapty returned an empty or invalid report.")
                    rows = normalize_report(endpoint, page[0], day, charts[index])
                    next_day = day + timedelta(days=1) if index + 1 == len(charts) else day
                    next_index = 0 if index + 1 == len(charts) else index + 1
                    manager.save_state(
                        AdaptyResumeConfig(
                            next_date=next_day.isoformat(), end_date=end.isoformat(), chart_index=next_index
                        )
                    )
                    if rows:
                        yield rows
                    else:
                        manager.safe_point()
            day += timedelta(days=1)
            chart_index = 0
    finally:
        client.session.close()


def adapty_source(
    config: AdaptySourceConfig, manager: ResumableSourceManager[AdaptyResumeConfig], inputs: SourceInputs
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    items: Callable[[], Iterable[Any]]
    if endpoint.shape == "paywalls":
        resume = manager.load_state() if manager.can_resume() else None
        api_config: RESTAPIConfig = {
            "client": {
                "base_url": SERVER_BASE_URL,
                "auth": {
                    "type": "api_key",
                    "api_key": f"Api-Key {config.api_key}",
                    "name": "Authorization",
                    "location": "header",
                },
                "request_timeout": REQUEST_TIMEOUT,
                "retry_budget_seconds": RETRY_BUDGET_SECONDS,
                "retry_after_max_seconds": 60,
                "allowed_hosts": [],
                "allow_redirects": False,
            },
            "resources": [
                {
                    "name": inputs.schema_name,
                    "table_format": "delta",
                    "write_disposition": "replace",
                    "endpoint": {
                        "path": endpoint.path,
                        "params": {"page[size]": 100},
                        "data_selector": "data",
                        "data_selector_required": True,
                        "paginator": PageNumberPaginator(
                            base_page=1, page_param="page[number]", total_path="meta.pagination.pages"
                        ),
                    },
                }
            ],
        }

        def save_checkpoint(state: dict[str, Any] | None) -> None:
            if state is not None:
                manager.save_state(AdaptyResumeConfig(page=int(state["page"])))

        resource = rest_api_resource(
            api_config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state={"page": resume.page} if resume else None,
        )
        items = lambda: resource
    else:
        items = lambda: iter_reports(config, endpoint, manager)

    return SourceResponse(
        name=inputs.schema_name,
        items=items,
        on_complete=manager.clear_state,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=[endpoint.partition_key],
        partition_mode="datetime",
        partition_format="month",
        partition_count=1,
        partition_size=1,
        sort_mode=None if endpoint.shape == "paywalls" else "asc",
    )
