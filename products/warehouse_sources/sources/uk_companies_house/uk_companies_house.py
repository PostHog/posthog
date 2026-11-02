import re
import dataclasses
from collections.abc import Callable, Iterator
from typing import Any, Optional

from requests import Request, RequestException, Response
from requests.exceptions import HTTPError
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.settings import (
    BASE_URL,
    ENDPOINT_SPECS,
    ITEMS_PER_PAGE,
    REQUEST_TIMEOUT,
    EndpointSpec,
)

# Company numbers are eight characters at Companies House: digits, or a two letter registrar
# prefix (SC, NI, OC, OE, BR) followed by six characters.
COMPANY_NUMBER_PATTERN = re.compile(r"^[A-Z0-9]{8}$")

_SEPARATORS = re.compile(r"[\s,;]+")


@dataclasses.dataclass
class UkCompaniesHouseResumeConfig:
    """Where a sync got to across the configured company numbers.

    ``company_index`` is the position in the configured company number list, so resume relies on
    that list being the same one the job started with. It is, because resume state is keyed by
    job id and a job runs against a single snapshot of the source config.
    """

    company_index: int = 0
    start_index: int = 0


class CompaniesHouseOffsetPaginator(BasePaginator):
    """Offset pagination over ``start_index`` / ``items_per_page``.

    Advances by the number of rows actually returned rather than by the requested page size:
    Companies House caps ``items_per_page`` per endpoint and quietly returns fewer rows than
    asked for, so a fixed stride would step over the rows it did not send.
    """

    def __init__(
        self,
        total_key: str,
        items_per_page: int = ITEMS_PER_PAGE,
        start_index: int = 0,
    ) -> None:
        super().__init__()
        self.total_key = total_key
        self.items_per_page = items_per_page
        self.start_index = start_index

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def _apply(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["start_index"] = self.start_index
        request.params["items_per_page"] = self.items_per_page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return

        self.start_index += len(data)

        try:
            body = response.json()
        except Exception:
            body = None

        total = body.get(self.total_key) if isinstance(body, dict) else None
        if isinstance(total, int) and not isinstance(total, bool):
            self._has_next_page = self.start_index < total
            return

        # No usable total in the body, so a short page is the only end-of-results signal left.
        self._has_next_page = len(data) >= self.items_per_page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"start_index": self.start_index} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        start_index = state.get("start_index")
        if start_index:
            self.start_index = int(start_index)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"CompaniesHouseOffsetPaginator(start_index={self.start_index}, items_per_page={self.items_per_page})"


def parse_company_numbers(raw: Optional[str]) -> list[str]:
    """Split the configured company numbers and normalize them to the registry's eight character
    form. Purely numeric input is zero padded, which is how Companies House writes short numbers:
    company 6400 is 00006400."""
    numbers: list[str] = []
    seen: set[str] = set()
    for token in _SEPARATORS.split(raw or ""):
        candidate = token.strip().upper()
        if not candidate:
            continue
        if candidate.isdigit():
            candidate = candidate.zfill(8)
        if candidate in seen:
            continue
        seen.add(candidate)
        numbers.append(candidate)
    return numbers


def invalid_company_numbers(company_numbers: list[str]) -> list[str]:
    return [number for number in company_numbers if not COMPANY_NUMBER_PATTERN.match(number)]


def _client(api_key: str) -> RESTClient:
    # The key is the HTTP Basic username with a blank password, so `HttpBasicAuth.secret_values`
    # (which only reports the password) would not redact it. Pass a session that masks it directly.
    return RESTClient(
        base_url=BASE_URL,
        auth=HttpBasicAuth(username=api_key, password=""),
        session=make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=REQUEST_TIMEOUT,
    )


def _id_from_self_link(row: dict[str, Any]) -> Optional[str]:
    links = row.get("links")
    self_link = links.get("self") if isinstance(links, dict) else None
    if not isinstance(self_link, str):
        return None
    return self_link.rstrip("/").rsplit("/", 1)[-1] or None


def _normalize(row: dict[str, Any], spec: EndpointSpec, company_number: str) -> dict[str, Any]:
    normalized = dict(row)
    if spec.parent_field:
        normalized[spec.parent_field] = company_number
    if spec.id_from_self_link:
        normalized[spec.id_from_self_link] = _id_from_self_link(row)
    return normalized


def _rows_for_company(
    client: RESTClient,
    spec: EndpointSpec,
    company_number: str,
    logger: FilteringBoundLogger,
    resume_hook: Callable[[Optional[dict[str, Any]]], None],
    initial_paginator_state: Optional[dict[str, Any]],
) -> Iterator[list[dict[str, Any]]]:
    paginator: BasePaginator = (
        CompaniesHouseOffsetPaginator(total_key=spec.total_key) if spec.total_key else SinglePagePaginator()
    )

    pages = client.paginate(
        path=spec.path.format(company_number=company_number),
        paginator=paginator,
        data_selector=spec.data_selector,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )

    try:
        for page in pages:
            rows = [_normalize(row, spec, company_number) for row in page if isinstance(row, dict)]
            if rows:
                yield rows
    except HTTPError as e:
        status_code = e.response.status_code if e.response is not None else None
        if status_code == 404:
            # Companies House answers 404 both for a company that has nothing filed for this
            # resource (most companies have no charges, insolvency or exemptions) and for a
            # company number that does not exist. Neither should fail the whole table.
            logger.info(
                "Companies House returned no data for a company",
                company_number=company_number,
                path=spec.path,
            )
            return
        raise


def uk_companies_house_source(
    api_key: str,
    endpoint: str,
    company_numbers: list[str],
    resumable_source_manager: ResumableSourceManager[UkCompaniesHouseResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    spec = ENDPOINT_SPECS[endpoint]
    client = _client(api_key)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    first_index = resume.company_index if resume else 0
    seeded_start_index = resume.start_index if resume else 0

    for index, company_number in enumerate(company_numbers):
        if index < first_index:
            continue

        initial_paginator_state = (
            {"start_index": seeded_start_index} if (index == first_index and seeded_start_index) else None
        )

        def checkpoint(state: Optional[dict[str, Any]], _index: int = index) -> None:
            # `RESTClient.paginate` deep copies the paginator, so this hook is the only view onto
            # the copy's progress. Saving after each yielded page means a crash re-yields the last
            # page rather than skipping it.
            if state and state.get("start_index"):
                resumable_source_manager.save_state(
                    UkCompaniesHouseResumeConfig(company_index=_index, start_index=int(state["start_index"]))
                )

        yield from _rows_for_company(
            client,
            spec,
            company_number,
            logger,
            resume_hook=checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

        resumable_source_manager.save_state(UkCompaniesHouseResumeConfig(company_index=index + 1, start_index=0))

    resumable_source_manager.clear_state()


def validate_credentials(api_key: str, company_number: str) -> tuple[bool, str | None]:
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    try:
        response = session.get(
            f"{BASE_URL}/company/{company_number}",
            auth=(api_key, ""),
            timeout=REQUEST_TIMEOUT,
        )
    except RequestException as e:
        return False, f"Could not reach the Companies House API: {e}"

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Companies House rejected the API key. Check that it is a live Public Data API key."
    if response.status_code == 403:
        return (
            False,
            "This Companies House API key cannot read the Public Data API. Check the application type in the developer hub.",
        )
    if response.status_code == 404:
        return False, f"Companies House has no company with number {company_number}."
    if response.status_code == 429:
        return False, "Companies House rate limited the request. Wait a few minutes and try again."
    return False, f"Companies House API returned HTTP {response.status_code}."
