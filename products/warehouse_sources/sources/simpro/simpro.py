import re
import dataclasses
from collections.abc import Iterator
from datetime import timedelta
from typing import Any, Optional
from urllib.parse import urlsplit

from products.warehouse_sources.sources.sdk import (
    BearerTokenAuth,
    PartitionMode,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    make_tracked_session,
    parse_datetime_value,
)
from products.warehouse_sources.sources.simpro.settings import (
    BUILD_DOMAINS,
    COMPANY_ID_COLUMN,
    DATE_MODIFIED,
    DEFAULT_BUILD_DOMAIN,
    ENDPOINT_CONFIGS,
    PAGE_SIZE,
    PRIMARY_KEYS,
    SIMPRO_API_VERSION,
    SimproEndpointConfig,
)


@dataclasses.dataclass(frozen=True)
class SimproResumeConfig:
    company_id: int
    # None for endpoints without an `Archived` filter, else the pass the run was in.
    archived: Optional[bool]
    page: int


@dataclasses.dataclass(frozen=True)
class _Pass:
    company_id: int
    archived: Optional[bool]


class SimproBuildURLError(ValueError):
    pass


_BUILD_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def is_simpro_build_host(host: str) -> bool:
    return any(host.endswith(f".{domain}") and len(host) > len(domain) + 1 for domain in BUILD_DOMAINS)


def normalize_build_host(build: str) -> str:
    """Return the host of a Simpro build, given as a build name or as a build URL.

    The API key goes to this host, so only hosts on the Simpro build domains are accepted.
    """
    value = build.strip().lower()
    if _BUILD_NAME_RE.match(value):
        return f"{value}.{DEFAULT_BUILD_DOMAIN}"
    if "://" not in value:
        value = f"https://{value}"
    try:
        host = urlsplit(value).hostname or ""
    except ValueError:
        host = ""
    if not is_simpro_build_host(host):
        raise SimproBuildURLError(f"{build!r} is not a Simpro build URL")
    return host


def _base_url(host: str) -> str:
    return f"https://{host}/api/{SIMPRO_API_VERSION}"


def _make_client(host: str, api_key: str) -> RESTClient:
    return RESTClient(
        base_url=_base_url(host),
        auth=BearerTokenAuth(token=api_key),
        headers={"Accept": "application/json"},
        paginator=SinglePagePaginator(),
        allowed_hosts=[host],
    )


def _get_list(client: RESTClient, path: str, params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    pages = list(client.paginate(path=path, params=params))
    rows = pages[0] if pages else []
    if not isinstance(rows, list):
        raise ValueError(f"Simpro returned an unexpected response from {path}. Expected a JSON list.")
    return rows


def parse_company_id(company_id: Optional[str]) -> Optional[int]:
    if company_id is None or not company_id.strip():
        return None
    return int(company_id.strip())


def list_company_ids(client: RESTClient) -> list[int]:
    # Builds without multi-company setup list a single company with ID 0.
    return [
        int(company["ID"])
        for company in _get_list(client, "/companies/", {"pageSize": PAGE_SIZE})
        if company.get("ID") is not None
    ]


def date_modified_filter(db_incremental_field_last_value: Any) -> Optional[str]:
    """The `DateModified` search value for a watermark, or None to read everything.

    Simpro filters `DateModified` by day only and compares in the build's own timezone, so the
    filter starts one day before the watermark. The merge on the primary key drops the overlap.
    """
    watermark = parse_datetime_value(db_incremental_field_last_value)
    if watermark is None:
        return None
    return f"ge({(watermark.date() - timedelta(days=1)).isoformat()})"


def _passes(config: SimproEndpointConfig, company_ids: list[int]) -> list[_Pass]:
    archived_states: tuple[Optional[bool], ...] = (False, True) if config.archivable else (None,)
    return [_Pass(company_id, archived) for company_id in company_ids for archived in archived_states]


def _params(config: SimproEndpointConfig, simpro_pass: _Pass, page: int, date_filter: Optional[str]) -> dict[str, Any]:
    return {
        "pageSize": PAGE_SIZE,
        "page": page,
        # ID order keeps page boundaries stable while rows change during the run.
        "orderby": "ID",
        "columns": ",".join(config.columns) if config.columns else None,
        "Archived": None if simpro_pass.archived is None else str(simpro_pass.archived).lower(),
        DATE_MODIFIED: date_filter,
    }


def _iter_rows(
    host: str,
    api_key: str,
    config: SimproEndpointConfig,
    configured_company_id: Optional[int],
    date_filter: Optional[str],
    resumable_source_manager: ResumableSourceManager[SimproResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    client = _make_client(host, api_key)
    try:
        company_ids = [configured_company_id] if configured_company_id is not None else list_company_ids(client)
        passes = _passes(config, company_ids)
        if not passes:
            return

        pass_index, page = 0, 1
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        if resume is not None:
            resumed_pass = _Pass(resume.company_id, resume.archived)
            if resumed_pass in passes:
                pass_index, page = passes.index(resumed_pass), resume.page

        while pass_index < len(passes):
            simpro_pass = passes[pass_index]
            path = f"/companies/{simpro_pass.company_id}/{config.path}"
            rows = _get_list(client, path, _params(config, simpro_pass, page, date_filter))
            is_last_pass = pass_index == len(passes) - 1

            # A short page ends the pass. The cursor still points one page further on the last pass,
            # so a resume after the final page reads one empty page and stops.
            if len(rows) >= PAGE_SIZE or is_last_pass:
                next_pass_index, next_page = pass_index, page + 1
            else:
                next_pass_index, next_page = pass_index + 1, 1
            next_pass = passes[next_pass_index]
            resumable_source_manager.save_state(
                SimproResumeConfig(company_id=next_pass.company_id, archived=next_pass.archived, page=next_page)
            )

            if rows:
                yield [{**row, COMPANY_ID_COLUMN: simpro_pass.company_id} for row in rows]
            else:
                resumable_source_manager.safe_point()

            if len(rows) < PAGE_SIZE:
                pass_index, page = pass_index + 1, 1
            else:
                page += 1
    finally:
        client.session.close()


def simpro_source(
    build: str,
    api_key: str,
    company_id: Optional[str],
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[SimproResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ENDPOINT_CONFIGS[endpoint]
    host = normalize_build_host(build)
    configured_company_id = parse_company_id(company_id)
    date_filter = (
        date_modified_filter(db_incremental_field_last_value)
        if should_use_incremental_field and config.incremental
        else None
    )

    partition_mode: Optional[PartitionMode] = "datetime" if config.partition_key else None
    return SourceResponse(
        name=config.name,
        items=lambda: _iter_rows(host, api_key, config, configured_company_id, date_filter, resumable_source_manager),
        primary_keys=PRIMARY_KEYS,
        partition_keys=[config.partition_key] if config.partition_key else None,
        partition_mode=partition_mode,
    )


class SimproUnexpectedResponseError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class CredentialCheck:
    status_code: int
    company_ids: list[int]

    @property
    def ok(self) -> bool:
        return self.status_code == 200


def check_credentials(host: str, api_key: str) -> CredentialCheck:
    session = make_tracked_session(redact_values=(api_key,))
    try:
        response = session.get(
            f"{_base_url(host)}/companies/",
            params={"pageSize": PAGE_SIZE},
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=30,
        )
    finally:
        session.close()
    if response.status_code != 200:
        return CredentialCheck(status_code=response.status_code, company_ids=[])
    try:
        body = response.json()
    except ValueError as error:
        raise SimproUnexpectedResponseError(f"{host} returned a response that is not JSON") from error
    if not isinstance(body, list):
        raise SimproUnexpectedResponseError(f"{host} returned a company list that is not a JSON list")
    company_ids = [
        int(company["ID"]) for company in body if isinstance(company, dict) and company.get("ID") is not None
    ]
    return CredentialCheck(status_code=200, company_ids=company_ids)
