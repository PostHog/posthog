from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import OAuth2Auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.settings import (
    BASE_URL,
    ENDPOINTS,
    REPORT_DIMENSIONS,
    REPORT_METRICS,
    REPORT_ROW_LIMIT,
    TOKEN_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.criteo import CriteoSourceConfig


@frozen
class CriteoResumeConfig:
    finished: bool = False
    offset: int | None = None
    fanout_state: dict[str, Any] | None = None
    next_day: str | None = None
    end_day: str | None = None


def flatten_entity(row: dict[str, Any]) -> dict[str, Any]:
    attributes = row.get("attributes") or {}
    return {**attributes, **{key: value for key, value in row.items() if key != "attributes"}}


def report_start_date(config: CriteoSourceConfig) -> date:
    try:
        start = date.fromisoformat(config.start_date)
    except ValueError as error:
        raise ValueError("Enter the report start date as YYYY-MM-DD.") from error
    if start > datetime.now(UTC).date():
        raise ValueError("The report start date cannot be in the future.")
    if len(config.currency) != 3 or not config.currency.isascii() or not config.currency.isalpha():
        raise ValueError("Enter a three-letter report currency code, such as USD.")
    return start


class CriteoClient:
    def __init__(self, config: CriteoSourceConfig, api_version: str) -> None:
        self.config = config
        self.api_version = api_version
        self.auth = OAuth2Auth(token_url=TOKEN_URL, client_id=config.client_id, client_secret=config.client_secret)
        self.session = make_tracked_session(redact_values=self.auth.secret_values(), allow_redirects=False)
        self.session.hooks["response"] = [self.check_response]

    def client_config(self) -> ClientConfig:
        return {
            "base_url": f"{BASE_URL}/{self.api_version}/",
            "auth": self.auth,
            "session": self.session,
            "headers": {"Accept": "application/json"},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": (10, 60),
        }

    def endpoint_config(self, name: str) -> Endpoint:
        endpoint = ENDPOINTS[name]
        result: Endpoint = {
            "path": endpoint.path,
            "method": endpoint.method,
            "data_selector": "data",
            "data_selector_required": True,
            "paginator": OffsetPaginator(limit=endpoint.page_size, total_path=endpoint.total_path)
            if endpoint.page_size
            else SinglePagePaginator(),
        }
        if endpoint.method == "POST":
            result["json"] = (
                {"data": {"type": "AudienceSearch", "attributes": {}}} if name == "Audiences" else {"filters": {}}
            )
        return result

    @staticmethod
    def check_response(response: Response, *args: object, **kwargs: object) -> None:
        if response.status_code != 200:
            return
        try:
            payload = response.json()
        except ValueError:
            return
        if isinstance(payload, dict) and payload.get("errors"):
            errors = payload["errors"]
            if isinstance(errors, list) and any(
                isinstance(error, dict) and error.get("type") in ("access-control", "authentication", "authorization")
                for error in errors
            ):
                raise ValueError("Criteo denied access. Check the application permissions and advertiser consent.")
            raise ValueError("Criteo returned an error in the response.")

    def reports(
        self,
        inputs: SourceInputs,
        manager: ResumableSourceManager[CriteoResumeConfig],
        resume: CriteoResumeConfig | None,
    ) -> Iterator[list[dict[str, Any]]]:
        start = report_start_date(self.config)
        today = datetime.now(UTC).date()
        retention_start = (
            today.replace(year=today.year - 2)
            if not (today.month == 2 and today.day == 29)
            else date(today.year - 2, 2, 28)
        )
        start = max(start, retention_start)
        if inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
            watermark = parse_datetime_value(inputs.db_incremental_field_last_value)
            if watermark is None:
                raise ValueError("Invalid Criteo report watermark.")
            start = max(start, watermark.date())
        end = today
        if resume and resume.next_day and resume.end_day:
            start = date.fromisoformat(resume.next_day)
            end = date.fromisoformat(resume.end_day)
        client = RESTClient(
            base_url=f"{BASE_URL}/{self.api_version}/",
            auth=self.auth,
            session=self.session,
            headers={"Accept": "application/json"},
            allowed_hosts=[],
            allow_redirects=False,
            request_timeout=(10, 60),
        )
        while start <= end:
            body = {
                "advertiserIds": "",
                "startDate": start.isoformat(),
                "endDate": start.isoformat(),
                "dimensions": REPORT_DIMENSIONS,
                "metrics": REPORT_METRICS,
                "currency": self.config.currency.upper(),
                "format": "json",
                "timezone": "UTC",
            }
            pages = client.paginate(
                ENDPOINTS["CampaignStats"].path,
                method="POST",
                json=body,
                paginator=SinglePagePaginator(),
                data_selector="Rows",
                data_selector_required=True,
            )
            rows = next(pages)
            if len(rows) >= REPORT_ROW_LIMIT:
                raise ValueError("Criteo reached the daily report row limit. The report may be incomplete.")
            for row in rows:
                day = parse_datetime_value(row.get("Day"))
                if day is None or day.date() != start:
                    raise ValueError("Criteo returned a report row outside the requested day.")
                if not row.get("AdvertiserId") or not row.get("CampaignId"):
                    raise ValueError("Criteo returned a report row without an advertiser or campaign ID.")
                row["Day"] = day.date().isoformat()
            start += timedelta(days=1)
            manager.save_state(CriteoResumeConfig(next_day=start.isoformat(), end_day=end.isoformat()))
            if rows:
                yield rows
            manager.safe_point()

    def entities(
        self,
        inputs: SourceInputs,
        manager: ResumableSourceManager[CriteoResumeConfig],
        resume: CriteoResumeConfig | None,
    ) -> Iterable[Any]:
        endpoint = ENDPOINTS[inputs.schema_name]
        if endpoint.fanout:

            def save_fanout(state: dict[str, Any] | None) -> None:
                if state is not None:
                    manager.save_state(CriteoResumeConfig(fanout_state=state))

            child = build_dependent_resource(
                endpoint_configs=ENDPOINTS,
                child_endpoint=endpoint.name,
                fanout=endpoint.fanout,
                client_config=self.client_config(),
                path_format_values={},
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                db_incremental_field_last_value=None,
                parent_endpoint_extra=self.endpoint_config("Advertisers"),
                child_endpoint_extra=self.endpoint_config(endpoint.name),
                page_size_param=None,
                resume_hook=save_fanout,
                initial_paginator_state=resume.fanout_state if resume else None,
            )
            return cast(Resource, child).add_map(flatten_entity)

        def save_offset(state: dict[str, Any] | None) -> None:
            # Full refresh resumes append rows, so a terminal checkpoint prevents a duplicate final page.
            if state is None:
                manager.save_state(CriteoResumeConfig(finished=True))
            elif state.get("offset") is not None:
                manager.save_state(CriteoResumeConfig(offset=int(state["offset"])))

        rest_config: RESTAPIConfig = {
            "client": self.client_config(),
            "resources": [{"name": endpoint.name, "endpoint": self.endpoint_config(endpoint.name)}],
        }
        return rest_api_resource(
            rest_config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_offset,
            initial_paginator_state={"offset": resume.offset} if resume and resume.offset is not None else None,
        ).add_map(flatten_entity)

    def validate(self, schema_name: str | None) -> None:
        self.auth(Request("GET", BASE_URL).prepare())
        if schema_name is None:
            return
        endpoint = self.endpoint_config(schema_name)
        if schema_name == "CampaignStats":
            today = datetime.now(UTC).date().isoformat()
            endpoint.update(
                {
                    "data_selector": "Rows",
                    "json": {
                        "advertiserIds": "",
                        "startDate": today,
                        "endDate": today,
                        "dimensions": REPORT_DIMENSIONS,
                        "metrics": REPORT_METRICS,
                        "currency": self.config.currency.upper(),
                        "format": "json",
                        "timezone": "UTC",
                    },
                }
            )
        client = RESTClient(
            base_url=f"{BASE_URL}/{self.api_version}/",
            auth=self.auth,
            session=self.session,
            request_timeout=(5, 15),
            max_retry_attempts=1,
            allowed_hosts=[],
            allow_redirects=False,
        )
        if schema_name == "Ads":
            advertisers = next(
                client.paginate(
                    "advertisers/me", paginator=SinglePagePaginator(), data_selector="data", data_selector_required=True
                )
            )
            if not advertisers:
                return
            endpoint["path"] = ENDPOINTS["Ads"].path.replace("{advertiser-id}", str(int(advertisers[0]["id"])))
        next(
            client.paginate(
                path=endpoint["path"] or "",
                method=endpoint["method"] or "GET",
                json=endpoint.get("json"),
                paginator=OffsetPaginator(
                    limit=ENDPOINTS[schema_name].page_size, total_path=ENDPOINTS[schema_name].total_path
                )
                if ENDPOINTS[schema_name].page_size
                else SinglePagePaginator(),
                data_selector=endpoint["data_selector"],
                data_selector_required=True,
            )
        )


def criteo_source(
    config: CriteoSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[CriteoResumeConfig],
    api_version: str,
) -> SourceResponse:
    endpoint = ENDPOINTS[inputs.schema_name]
    client = CriteoClient(config, api_version)
    resume = manager.load_state() if manager.can_resume() else None
    reports = endpoint.name == "CampaignStats"
    items: Iterable[Any]
    if resume and resume.finished:
        items = ()
    else:
        items = client.reports(inputs, manager, resume) if reports else client.entities(inputs, manager, resume)
    return SourceResponse(
        name=endpoint.name,
        items=lambda: items,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=[endpoint.partition_key],
        partition_mode=endpoint.partition_mode,
        partition_format=endpoint.partition_format,
        partition_count=endpoint.partition_count,
        partition_size=1,
        sort_mode="asc" if reports else None,
    )
