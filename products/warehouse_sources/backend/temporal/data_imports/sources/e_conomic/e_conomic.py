import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import urlparse

from requests import PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_chained_resource,
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.settings import (
    E_CONOMIC_ENDPOINTS,
    E_CONOMIC_FANOUT_PARENTS,
    PAGE_SIZE,
)

E_CONOMIC_BASE_URL = "https://restapi.e-conomic.com"
E_CONOMIC_HOST = urlparse(E_CONOMIC_BASE_URL).netloc


@dataclasses.dataclass(frozen=True)
class EConomicResumeConfig:
    # Full URL of the next page to fetch. The API's pagination links already carry pagesize, sort and
    # filter, so resuming is just "GET this URL".
    next_url: str | None = None
    # Fan-out endpoints instead checkpoint which parents finished and where the current one stopped.
    fanout_state: Optional[dict[str, Any]] = None


def _headers() -> dict[str, str]:
    # Only the non-secret content-type header lives here; the two credential tokens are supplied via
    # EConomicTokenAuth so their values are redacted from logs and raised error messages.
    return {"Content-Type": "application/json"}


def _assert_trusted_url(url: str) -> None:
    """Guard against following a pagination/resume URL off the e-conomic host.

    Every request carries `X-AppSecretToken`/`X-AgreementGrantToken`, so a `nextPage` link or persisted
    resume URL pointing anywhere other than the API host (or over plain http) would leak those tokens.
    We only ever fetch HATEOAS links the API itself returns (or our own resume state), so anything
    off-host or non-https is unexpected and we abort rather than send credentials to it.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != E_CONOMIC_HOST:
        raise ValueError(f"Refusing to fetch untrusted e-conomic URL: {url}")


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value for an e-conomic `filter` expression.

    Datetimes go out as UTC `...Z` (the format the API returns and accepts), dates as `YYYY-MM-DD`,
    and monotonic integer cursors (e.g. bookedInvoiceNumber) as their plain decimal string.
    """
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


class EConomicTokenAuth(AuthConfigBase):
    """Sends e-conomic's two credential headers and marks both for log / error-message redaction.

    e-conomic has no bearer/basic scheme: it authenticates every request with two custom headers.
    Declaring both here (rather than as plain client headers) is what lets the tracked transport and
    the client's exception scrubber redact their values wherever they surface.
    """

    def __init__(self, app_secret_token: str, agreement_grant_token: str) -> None:
        self.app_secret_token = app_secret_token
        self.agreement_grant_token = agreement_grant_token

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["X-AppSecretToken"] = self.app_secret_token
        request.headers["X-AgreementGrantToken"] = self.agreement_grant_token
        return request

    def secret_values(self) -> tuple[str, ...]:
        return tuple(value for value in (self.app_secret_token, self.agreement_grant_token) if value)


class EConomicNextPagePaginator(JSONResponsePaginator):
    """Follows e-conomic's `pagination.nextPage` HATEOAS link, refusing any off-host / non-https link.

    The API returns absolute next-page URLs; validating each before it is fetched keeps the credential
    headers from ever leaving the e-conomic host, reproducing the hand-rolled source's guard. Resume is
    inherited from the base next-URL paginator (state is `{"next_url": ...}`).
    """

    def __init__(self) -> None:
        super().__init__(next_url_path="pagination.nextPage")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and self._next_url is not None:
            _assert_trusted_url(self._next_url)


RowMap = Callable[[dict[str, Any]], dict[str, Any]]


def _add_link_path(link: str) -> RowMap:
    # Accounting years spanning two calendar years use a different form in URLs than their `year`, so
    # child paths come from the links the API returns.
    def _mapper(row: dict[str, Any]) -> dict[str, Any]:
        row[f"{link}_path"] = urlparse(row[link]).path
        return row

    return _mapper


def _add_period_fields(row: dict[str, Any]) -> dict[str, Any]:
    row["totals_path"] = urlparse(row["totals"]).path
    row["year"] = row["accountingYear"]["year"]
    return row


def _add_account_number(row: dict[str, Any]) -> dict[str, Any]:
    row["accountNumber"] = row["account"]["accountNumber"]
    return row


def _flatten_accounting_year(row: dict[str, Any]) -> dict[str, Any]:
    row["accountingYear"] = row["accountingYear"]["year"]
    return row


_PARENT_DATA_MAPS: dict[str, RowMap] = {
    "accounting_year_entries": _add_link_path("entries"),
    "accounting_year_totals": _add_link_path("totals"),
}

# Lift the ids out of nested reference objects so they can be primary keys.
_CHILD_DATA_MAPS: dict[str, RowMap] = {
    "accounting_year_totals": _add_account_number,
    "accounting_period_totals": _add_account_number,
    "journal_vouchers": _flatten_accounting_year,
}


def _client_config(app_secret_token: str, agreement_grant_token: str) -> ClientConfig:
    return {
        "base_url": E_CONOMIC_BASE_URL,
        "headers": _headers(),
        "auth": EConomicTokenAuth(app_secret_token, agreement_grant_token),
        "paginator": EConomicNextPagePaginator(),
        # Pin every request — including next-page and seeded resume URLs — to the API host, and
        # refuse redirects, so the credential headers can never be carried off-host.
        "allowed_hosts": [E_CONOMIC_HOST],
        "allow_redirects": False,
    }


def _resolve(resource: str, field: str) -> dict[str, Any]:
    return {"type": "resolve", "resource": resource, "field": field}


def _period_totals_resource(
    endpoint: str,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
) -> Resource:
    """Build accounting_years -> periods -> totals. A two-hop chain carries no resume state."""
    config = E_CONOMIC_ENDPOINTS[endpoint]
    fanout = config.fanout
    assert fanout is not None
    periods = E_CONOMIC_FANOUT_PARENTS[fanout.parent_name]
    periods_fanout = periods.fanout
    assert periods_fanout is not None
    years = E_CONOMIC_ENDPOINTS[periods_fanout.parent_name]

    resources: list[EndpointResource] = [
        {
            "name": years.name,
            "table_name": years.name,
            "write_disposition": "replace",
            "endpoint": {
                "path": years.path,
                "params": {"pagesize": years.page_size, **periods_fanout.parent_params},
                "data_selector": "collection",
            },
            "data_map": _add_link_path("periods"),
            "table_format": "delta",
        },
        {
            "name": periods.name,
            "table_name": periods.name,
            "write_disposition": "replace",
            "endpoint": {
                "path": periods.path,
                "params": {
                    "pagesize": periods.page_size,
                    periods_fanout.resolve_param: _resolve(years.name, periods_fanout.resolve_field),
                },
                "data_selector": "collection",
                "paginator": EConomicNextPagePaginator(),
            },
            "data_map": _add_period_fields,
            "table_format": "delta",
        },
        {
            "name": endpoint,
            "table_name": endpoint,
            "write_disposition": "replace",
            "include_from_parent": fanout.include_from_parent,
            "endpoint": {
                "path": config.path,
                "params": {
                    "pagesize": config.page_size,
                    fanout.resolve_param: _resolve(periods.name, fanout.resolve_field),
                },
                "data_selector": "collection",
                "paginator": EConomicNextPagePaginator(),
            },
            "table_format": "delta",
        },
    ]
    return cast(
        Resource,
        build_chained_resource(
            resources=resources,
            child_name=endpoint,
            parent_name=periods.name,
            parent_field_renames=fanout.parent_field_renames,
            client_config=client_config,
            team_id=team_id,
            job_id=job_id,
        ),
    )


def e_conomic_source(
    app_secret_token: str,
    agreement_grant_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[EConomicResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = E_CONOMIC_ENDPOINTS[endpoint]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.fanout is not None:
        client_config = _client_config(app_secret_token, agreement_grant_token)
        if config.fanout.parent_name in E_CONOMIC_FANOUT_PARENTS:
            child = _period_totals_resource(endpoint, client_config, team_id, job_id)
        else:

            def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
                if state:
                    resumable_source_manager.save_state(EConomicResumeConfig(fanout_state=state))

            child = cast(
                Resource,
                build_dependent_resource(
                    endpoint_configs=E_CONOMIC_ENDPOINTS,
                    child_endpoint=endpoint,
                    fanout=config.fanout,
                    client_config=client_config,
                    parent_data_map=_PARENT_DATA_MAPS.get(endpoint),
                    parent_endpoint_extra={"data_selector": "collection"},
                    # Explicit, because the framework treats a path ending in a placeholder ("{entries_path}") as a
                    # single-entity lookup and would otherwise fetch only its first page.
                    child_endpoint_extra={"data_selector": "collection", "paginator": EConomicNextPagePaginator()},
                    page_size_param="pagesize",
                    path_format_values={},
                    team_id=team_id,
                    job_id=job_id,
                    db_incremental_field_last_value=None,
                    resume_hook=save_fanout_checkpoint,
                    initial_paginator_state=resume.fanout_state if resume else None,
                ),
            )

        child_map = _CHILD_DATA_MAPS.get(endpoint)
        if child_map is not None:
            child.add_map(child_map)
        return SourceResponse(
            name=endpoint,
            items=lambda: child,
            primary_keys=config.primary_keys,
            sort_mode=None,
            partition_mode="datetime" if config.partition_key else None,
            partition_format="month" if config.partition_key else None,
            partition_keys=[config.partition_key] if config.partition_key else None,
        )

    params: dict[str, Any] = {"pagesize": PAGE_SIZE}
    if config.sort:
        params["sort"] = config.sort

    # Server-side incremental filter. `>=` (re-fetching the boundary row) is safe because merge dedupes
    # on the primary key, and it avoids missing rows that share the cursor value. The pagination links
    # the API returns carry this filter forward, so it only needs setting on the first request.
    if should_use_incremental_field and incremental_field and db_incremental_field_last_value is not None:
        formatted = _format_incremental_value(db_incremental_field_last_value)
        params["filter"] = f"{incremental_field}$gte:{formatted}"

    rest_config: RESTAPIConfig = {
        "client": _client_config(app_secret_token, agreement_grant_token),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A missing/empty `collection` is a legitimate zero-row page (the API omits it when
                    # there is nothing to return), so this is intentionally not `data_selector_required`.
                    "data_selector": "collection",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.next_url:
        initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; saved AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(EConomicResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Ascending order only holds when we send a sort field; endpoints with no sortable column
        # (e.g. payment_terms) return rows in an unspecified order, so we don't claim a sort mode.
        sort_mode="asc" if config.sort else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(app_secret_token: str, agreement_grant_token: str) -> bool:
    """Probe the cheap `/self` endpoint. Any non-200 (the API returns 401 for a bad app-secret OR
    agreement-grant token) means the credentials are unusable."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(app_secret_token, agreement_grant_token)),
        f"{E_CONOMIC_BASE_URL}/self",
        headers={
            "X-AppSecretToken": app_secret_token,
            "X-AgreementGrantToken": agreement_grant_token,
            **_headers(),
        },
        # Credentials ride in custom headers that requests won't strip on a cross-origin redirect,
        # so a redirect from /self would replay both tokens to its Location — don't follow one.
        allow_redirects=False,
    )
    return ok
