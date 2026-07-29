import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gusto.settings import (
    GUSTO_ENDPOINTS,
    GustoEndpointConfig,
)

# Gusto runs a separate demo environment with its own credentials; partner apps build against demo
# until Gusto approves them for production.
GUSTO_HOSTS = {
    "production": "https://api.gusto.com",
    "demo": "https://api.gusto-demo.com",
}
DEFAULT_ENVIRONMENT = "production"
# Dated API version pinned via the `X-Gusto-API-Version` header. Everything below is written
# against this contract; bumping it is a `warehouse-source-new-version` change.
GUSTO_API_VERSION = "2024-04-01"

REQUEST_TIMEOUT_SECONDS = 60
# Source creation runs this synchronously, so keep the credential probe snappy.
VALIDATE_TIMEOUT_SECONDS = 15
# Gusto's collections default to 25 rows per page and cap `per` at 100.
PAGE_SIZE = 100
# Guard against a malformed pagination header looping forever on a single company.
MAX_PAGES_PER_COMPANY = 2000
# Gusto (then ZenPayroll) ran its first payrolls in 2012, so nothing predates this window.
DEFAULT_WINDOW_START = "2011-01-01"
# Payrolls and pay periods are scheduled ahead of today, so the window has to reach forward.
FUTURE_WINDOW_DAYS = 365
# Rows for the date-windowed endpoints are buffered to sort them, then handed over in chunks.
WINDOW_CHUNK_SIZE = 1000


@dataclasses.dataclass
class GustoResumeConfig:
    # Index into the ordered company list to restart at.
    company_index: int = 0
    # Next 1-indexed page to fetch within that company.
    next_page: int = 1
    # For endpoints fanned out over employees: index into that company's ordered employee list.
    employee_index: int = 0


class GustoClient:
    """Bearer-auth client that mints its own short-lived access token.

    Gusto issues 2 hour access tokens from an authorization-code refresh token, so the token is
    minted at the start of a sync and re-minted once on a 401 in case a long sync outlives it.
    """

    def __init__(
        self,
        environment: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        api_version: str,
        logger: Optional[FilteringBoundLogger] = None,
    ) -> None:
        self._host = base_url(environment)
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._logger = logger
        self._token: Optional[str] = None
        self._session = make_tracked_session(
            headers={"Accept": "application/json", "X-Gusto-API-Version": api_version},
            redact_values=(client_secret, refresh_token),
            # Gusto responses carry HR/payroll PII (names, emails, DOBs, addresses, pay rates) that
            # the name-based scrubber can't reliably strip, so keep bodies out of HTTP sample capture.
            capture=False,
        )

    @property
    def logger(self) -> Optional[FilteringBoundLogger]:
        return self._logger

    def mint_token(self, timeout: int = REQUEST_TIMEOUT_SECONDS) -> str:
        response = self._session.post(
            f"{self._host}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise ValueError("Gusto did not return an access token for the supplied refresh token")
        self._token = str(token)
        return self._token

    def request(self, path: str, params: Optional[dict[str, Any]] = None) -> requests.Response:
        url = f"{self._host}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        if self._token is None:
            self.mint_token()

        def _do() -> requests.Response:
            return self._session.get(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        response = _do()
        # Access tokens last two hours; a long sync can outlive one, so re-mint once and retry.
        if response.status_code == 401:
            self.mint_token()
            response = _do()

        if not response.ok:
            if self._logger is not None:
                self._logger.error(f"Gusto API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response

    def get_json(self, path: str, params: Optional[dict[str, Any]] = None) -> tuple[Any, requests.Response]:
        response = self.request(path, params)
        return response.json(), response


def base_url(environment: str) -> str:
    host = GUSTO_HOSTS.get(environment or DEFAULT_ENVIRONMENT)
    if host is None:
        raise ValueError(f"Invalid Gusto environment: {environment!r}. Expected one of {sorted(GUSTO_HOSTS)}.")
    return host


def extract_next_page(response: requests.Response, page: int, item_count: int) -> Optional[int]:
    """Resolve the next 1-indexed page, or None when the collection is exhausted.

    Gusto's paginated collections return `X-Total-Pages` alongside `X-Page`. Some newer endpoints
    ship `X-Has-Next-Page` instead, and a few return neither — a short page then means the end.
    """
    has_next = response.headers.get("X-Has-Next-Page")
    if has_next is not None:
        return page + 1 if has_next.strip().lower() == "true" else None

    total_pages = response.headers.get("X-Total-Pages")
    if total_pages is not None:
        try:
            return page + 1 if page < int(total_pages) else None
        except ValueError:
            pass

    return page + 1 if item_count >= PAGE_SIZE else None


def list_companies(client: GustoClient) -> list[dict[str, Any]]:
    """Companies the access token can reach, from the token holder's roles on `/v1/me`.

    Ordered by uuid so a resumed sync walks the same companies in the same order.
    """
    body, _ = client.get_json("/v1/me")
    if not isinstance(body, dict):
        raise ValueError(f"Gusto returned an unexpected /v1/me payload: {type(body).__name__}")

    companies: dict[str, dict[str, Any]] = {}
    roles = body.get("roles")
    if isinstance(roles, dict):
        for role in roles.values():
            if not isinstance(role, dict):
                continue
            for company in role.get("companies") or []:
                if not isinstance(company, dict):
                    continue
                uuid = company.get("uuid") or company.get("id")
                if uuid is not None:
                    companies[str(uuid)] = company

    return [companies[uuid] for uuid in sorted(companies)]


def _window_bounds(db_incremental_field_last_value: Optional[Any]) -> tuple[str, str]:
    end = (datetime.now(UTC).date() + timedelta(days=FUTURE_WINDOW_DAYS)).isoformat()
    if db_incremental_field_last_value is None:
        return DEFAULT_WINDOW_START, end

    raw = db_incremental_field_last_value
    if isinstance(raw, datetime | date):
        return raw.isoformat()[:10], end
    return str(raw)[:10] or DEFAULT_WINDOW_START, end


def _stamp_parents(rows: list[dict[str, Any]], parents: dict[str, str]) -> list[dict[str, Any]]:
    return [{**row, **parents} for row in rows]


def _normalize_rows(config: GustoEndpointConfig, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if config.name != "payrolls":
        return rows
    # Payroll objects key their identifier as `payroll_uuid`; mirror a bare `uuid` into it so the
    # declared primary key is always populated.
    return [
        row if "payroll_uuid" in row else {**row, "payroll_uuid": row.get("uuid")}
        for row in rows
        if isinstance(row, dict)
    ]


def extract_rows(config: GustoEndpointConfig, body: Any) -> list[dict[str, Any]]:
    """Pull the row list out of a Gusto response body."""
    if isinstance(body, list):
        return _normalize_rows(config, [row for row in body if isinstance(row, dict)])

    if not isinstance(body, dict):
        return []

    if config.data_key is None:
        return _normalize_rows(config, [body])

    rows: list[dict[str, Any]] = []
    for group in body.get(config.data_key) or []:
        if not isinstance(group, dict):
            continue
        payments = group.get("payments")
        if isinstance(payments, list):
            # Contractor payments arrive grouped per contractor; the individual payments are the
            # rows, and only the group carries the contractor identifier.
            for payment in payments:
                if isinstance(payment, dict):
                    rows.append({"contractor_uuid": group.get("contractor_uuid"), **payment})
        else:
            rows.append(group)

    return _normalize_rows(config, rows)


def _paginate(
    client: GustoClient,
    config: GustoEndpointConfig,
    path: str,
    parents: dict[str, str],
    first_page: int,
    extra_params: Optional[dict[str, Any]] = None,
    on_page: Optional[Callable[[int], None]] = None,
) -> Iterator[list[dict[str, Any]]]:
    page = max(first_page, 1)
    for _ in range(MAX_PAGES_PER_COMPANY):
        params: dict[str, Any] = {"page": page, "per": PAGE_SIZE, **(extra_params or {})}
        body, response = client.get_json(path, params)
        rows = _stamp_parents(extract_rows(config, body), parents)
        if rows:
            yield rows

        next_page = extract_next_page(response, page, len(rows))
        if next_page is None or not rows:
            return

        page = next_page
        if on_page is not None:
            # Checkpoint AFTER yielding so a crash re-fetches the next page rather than skipping it.
            on_page(page)

    if client.logger is not None:
        client.logger.warning(f"Gusto page cap reached, stopping early. endpoint={config.name}, path={path}")


def _company_employees(client: GustoClient, company_uuid: str) -> list[dict[str, Any]]:
    """Every employee of a company, ordered by uuid so fan-out resumes deterministically."""
    config = GUSTO_ENDPOINTS["employees"]
    path = config.path.format(company_uuid=company_uuid)
    employees: list[dict[str, Any]] = []
    for batch in _paginate(client, config, path, {}, first_page=1):
        employees.extend(batch)
    return sorted(employees, key=lambda employee: str(employee.get("uuid") or ""))


def _windowed_rows(
    client: GustoClient,
    config: GustoEndpointConfig,
    companies: list[dict[str, Any]],
    start_date: str,
    end_date: str,
) -> Iterator[list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    window = {"start_date": start_date, "end_date": end_date}

    for company in companies:
        company_uuid = str(company.get("uuid") or company.get("id"))
        path = config.path.format(company_uuid=company_uuid)
        parents = {"_company_uuid": company_uuid}
        if config.paginated:
            for batch in _paginate(client, config, path, parents, first_page=1, extra_params=window):
                rows.extend(batch)
        else:
            body, _ = client.get_json(path, window)
            rows.extend(_stamp_parents(extract_rows(config, body), parents))

    # Gusto documents no ordering for these collections, and the pipeline advances the incremental
    # watermark after every batch — so sort on the cursor field to make `sort_mode="asc"` true.
    cursor = config.date_window_field or ""
    rows.sort(key=lambda row: str(row.get(cursor) or ""))

    for index in range(0, len(rows), WINDOW_CHUNK_SIZE):
        yield rows[index : index + WINDOW_CHUNK_SIZE]


def get_rows(
    environment: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    endpoint: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GustoResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = GUSTO_ENDPOINTS[endpoint]
    client = GustoClient(environment, client_id, client_secret, refresh_token, api_version, logger)
    companies = list_companies(client)

    if config.date_window_field is not None:
        start_date, end_date = _window_bounds(db_incremental_field_last_value)
        # The whole window is buffered so it can be sorted, so there is no partial state worth
        # checkpointing here — a retry simply re-requests the window.
        yield from _windowed_rows(client, config, companies, start_date, end_date)
        return

    def checkpoint_page(company_index: int) -> Callable[[int], None]:
        def save(page: int) -> None:
            resumable_source_manager.save_state(GustoResumeConfig(company_index=company_index, next_page=page))

        return save

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        logger.debug(
            f"Gusto: resuming {endpoint} from company_index={resume.company_index}, "
            f"page={resume.next_page}, employee_index={resume.employee_index}"
        )

    for company_index, company in enumerate(companies):
        if resume is not None and company_index < resume.company_index:
            continue

        resuming_here = resume is not None and company_index == resume.company_index
        company_uuid = str(company.get("uuid") or company.get("id"))
        parents = {"_company_uuid": company_uuid}

        if endpoint == "companies":
            body, _ = client.get_json(config.path.format(company_uuid=company_uuid))
            rows = extract_rows(config, body)
            if rows:
                yield rows
        elif config.fans_out_over_employees:
            employees = _company_employees(client, company_uuid)
            first_employee = resume.employee_index if (resuming_here and resume is not None) else 0
            for employee_index, employee in enumerate(employees):
                if employee_index < first_employee:
                    continue
                employee_uuid = str(employee.get("uuid") or "")
                body, _ = client.get_json(config.path.format(employee_uuid=employee_uuid))
                rows = _stamp_parents(extract_rows(config, body), {**parents, "_employee_uuid": employee_uuid})
                if rows:
                    yield rows
                resumable_source_manager.save_state(
                    GustoResumeConfig(company_index=company_index, employee_index=employee_index + 1)
                )
        else:
            first_page = resume.next_page if (resuming_here and resume is not None) else 1
            yield from _paginate(
                client,
                config,
                config.path.format(company_uuid=company_uuid),
                parents,
                first_page=first_page,
                on_page=checkpoint_page(company_index),
            )

        resumable_source_manager.save_state(GustoResumeConfig(company_index=company_index + 1))


def gusto_source(
    environment: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    endpoint: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GustoResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = GUSTO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            environment=environment,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            endpoint=endpoint,
            api_version=api_version,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )


def validate_credentials(
    environment: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    api_version: str,
) -> tuple[bool, str | None]:
    """Mint an access token and read `/v1/me` to confirm the app credentials work."""
    try:
        client = GustoClient(environment, client_id, client_secret, refresh_token, api_version)
    except ValueError as e:
        return False, str(e)

    try:
        client.mint_token(timeout=VALIDATE_TIMEOUT_SECONDS)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status in (400, 401):
            return (
                False,
                "Gusto rejected these OAuth credentials. Check the client ID and secret, and note that Gusto "
                "rotates refresh tokens — a token that has already been exchanged no longer works.",
            )
        return False, f"Gusto returned HTTP {status} when requesting an access token"
    except ValueError as e:
        return False, str(e)
    except Exception:
        return False, "Could not connect to Gusto. Check the environment and try again."

    try:
        companies = list_companies(client)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 403:
            return False, "This Gusto token is not authorized to read company data. Reconnect with a payroll admin."
        return False, f"Gusto returned HTTP {status} when listing companies"
    except Exception:
        return False, "Could not read companies from Gusto"

    if not companies:
        return False, "This Gusto token has no companies attached to it. Authorize it against a company and retry."

    return True, None
