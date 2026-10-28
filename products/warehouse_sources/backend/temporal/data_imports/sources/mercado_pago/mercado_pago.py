from datetime import UTC, datetime, timedelta
from typing import Any

from requests.exceptions import HTTPError
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mercadopago import (
    MercadoPagoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
    PARTITION_KEYS,
    PRIMARY_KEYS,
)


@frozen
class MercadoPagoResumeConfig:
    offset: int
    begin_date: str | None = None
    end_date: str | None = None


def validate_credentials(config: MercadoPagoSourceConfig) -> tuple[bool, str | None]:
    with make_tracked_session(retry=Retry(total=0), redact_values=(config.access_token,)) as session:
        client = RESTClient(
            base_url=BASE_URL,
            auth=BearerTokenAuth(config.access_token),
            paginator=SinglePagePaginator(),
            session=session,
            max_retry_attempts=1,
            request_timeout=30,
        )
        try:
            next(client.paginate(ENDPOINTS["payments"], params={"limit": 1}, data_selector="results"))
        except HTTPError as error:
            if error.response is not None and error.response.status_code in (401, 403):
                return False, AUTH_ERROR
            raise
    return True, None


def mercado_pago_source(
    config: MercadoPagoSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[MercadoPagoResumeConfig],
) -> SourceResponse:
    path = schema_for_resource(ENDPOINTS, inputs.schema_name)
    resume = manager.load_state() if manager.can_resume() else None
    params: dict[str, Any] = {}
    begin_date: str | None = None
    end_date: str | None = None
    if inputs.schema_name == "payments":
        if resume is not None and resume.begin_date is not None and resume.end_date is not None:
            begin_date, end_date = resume.begin_date, resume.end_date
        else:
            end = datetime.now(UTC)
            end = end.replace(microsecond=end.microsecond // 1000 * 1000)
            # Payment searches reject intervals of 365 days or more.
            begin = end - timedelta(days=365) + timedelta(milliseconds=1)
            if inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
                last_value = inputs.db_incremental_field_last_value
                cursor = last_value if isinstance(last_value, datetime) else datetime.fromisoformat(str(last_value))
                if cursor.tzinfo is None:
                    cursor = cursor.replace(tzinfo=UTC)
                begin = max(begin, cursor.astimezone(UTC))
            begin_date = begin.isoformat(timespec="milliseconds")
            end_date = end.isoformat(timespec="milliseconds")
        params = {
            "range": "date_last_updated" if inputs.should_use_incremental_field else "date_created",
            "sort": "date_last_updated" if inputs.should_use_incremental_field else "date_created",
            "criteria": "asc",
            "begin_date": begin_date,
            "end_date": end_date,
        }

    endpoint: Endpoint = {
        "path": path,
        "params": params,
        "data_selector": "results",
        "data_selector_required": True,
    }
    resource_config: EndpointResource = {
        "name": inputs.schema_name,
        "table_format": "delta",
        "endpoint": endpoint,
    }
    api_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": config.access_token},
            "paginator": {"type": "offset", "limit": PAGE_SIZE, "total_path": "paging.total"},
            "request_timeout": 30,
        },
        "resources": [resource_config],
    }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(
                MercadoPagoResumeConfig(offset=int(state["offset"]), begin_date=begin_date, end_date=end_date)
            )

    resource = rest_api_resource(
        api_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"offset": resume.offset} if resume is not None else None,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS,
        partition_keys=PARTITION_KEYS,
        partition_mode="datetime",
        partition_format="month",
        sort_mode="asc" if inputs.schema_name == "payments" else "desc",
        on_complete=manager.clear_state,
    )
