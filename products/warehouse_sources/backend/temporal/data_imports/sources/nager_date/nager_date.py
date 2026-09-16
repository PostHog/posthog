import re
import datetime
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import quote

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.nager_date.settings import (
    COUNTRIES,
    COUNTRY_INFO,
    NEXT_PUBLIC_HOLIDAYS,
    PUBLIC_HOLIDAYS,
)

BASE_URL = "https://date.nager.at/api/v4"

REQUEST_TIMEOUT_SECONDS = 30

# The community API only serves a rolling window of years around today for PublicHolidays;
# requesting outside it returns HTTP 400 rather than an empty list. Verified live (2026-08-18):
# the US, GB, DE, FR, JP, and BR all accepted 2025-2031 and rejected 2024 and 2032, i.e. the
# current year minus 1 through plus 5. This isn't documented in the OpenAPI spec, so `_get` also
# treats an out-of-window 400 as "no data" rather than an error, in case the window shifts.
BACKFILL_YEARS_BACK = 1
FORWARD_YEARS = 5

# Bounds fan-out: the API lists 200+ countries, and every configured country costs one request
# per synced year for PublicHolidays, plus one each for CountryInfo and NextPublicHolidays.
MAX_COUNTRY_CODES = 50

_CODE_SEPARATORS = re.compile(r"[,\s]+")
_COUNTRY_CODE_RE = re.compile(r"^[A-Za-z]{2}$")


@dataclasses.dataclass(frozen=True)
class NagerDateResumeConfig:
    # Position in the endpoint's flattened work list (countries, or country/year pairs).
    index: int = 0


def parse_country_codes(raw: Optional[str]) -> list[str]:
    """Parse the user's free-text `country_codes` field into a deduplicated, uppercased list.

    Accepts one code per line and/or comma-separated codes.
    """
    codes: list[str] = []
    seen: set[str] = set()
    for token in _CODE_SEPARATORS.split(raw or ""):
        code = token.strip().upper()
        if not code:
            continue
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def check_country_codes(country_codes: list[str]) -> Optional[str]:
    """User-facing error if the configured country code list is empty, oversized, or malformed."""
    if not country_codes:
        return "Enter at least one ISO 3166-1 alpha-2 country code, for example US."
    if len(country_codes) > MAX_COUNTRY_CODES:
        return f"Too many country codes ({len(country_codes)}); enter at most {MAX_COUNTRY_CODES}."
    invalid = [code for code in country_codes if not _COUNTRY_CODE_RE.match(code)]
    if invalid:
        return f"These aren't valid two-letter country codes: {', '.join(invalid)}."
    return None


def _holiday_years() -> list[int]:
    current_year = datetime.date.today().year
    return list(range(current_year - BACKFILL_YEARS_BACK, current_year + FORWARD_YEARS + 1))


def _holiday_id(row: dict[str, Any]) -> str:
    """Synthetic key for a holiday row: (countryCode, date, name) alone isn't unique — the same
    holiday can appear twice with different subdivisionCodes/holidayTypes (e.g. Good Friday is a
    public holiday in some US states and an optional holiday in Texas)."""
    subdivisions = ",".join(sorted(row.get("subdivisionCodes") or []))
    types = ",".join(sorted(row.get("holidayTypes") or []))
    return f"{row.get('countryCode')}|{row.get('date')}|{row.get('name')}|{subdivisions}|{types}"


def _with_holiday_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**row, "id": _holiday_id(row)} for row in rows]


def _get(session: requests.Session, path: str) -> Any:
    """GET a Nager.Date v4 path, treating "no data for this request" as `None`.

    204: the country has no holiday data at all. 400: the requested year is outside the community
    API's supported rolling window. 404: the country code isn't recognized (validate_credentials
    should already have caught this at source-create).
    """
    response = session.get(f"{BASE_URL}{path}", timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code in (204, 400, 404):
        return None
    response.raise_for_status()
    if not response.content:
        return None
    return response.json()


def _countries_rows(session: requests.Session) -> Iterator[list[dict[str, Any]]]:
    data = _get(session, "/Countries/Available")
    if data:
        yield data


def _country_info_rows(
    session: requests.Session,
    country_codes: list[str],
    resumable_source_manager: ResumableSourceManager[NagerDateResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = resume.index if resume is not None else 0

    for index, country_code in enumerate(country_codes):
        if index < start_index:
            continue
        data = _get(session, f"/Countries/{quote(country_code, safe='')}")
        if data:
            yield [data]
        resumable_source_manager.save_state(NagerDateResumeConfig(index=index + 1))


def _next_public_holidays_rows(
    session: requests.Session,
    country_codes: list[str],
    resumable_source_manager: ResumableSourceManager[NagerDateResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = resume.index if resume is not None else 0

    for index, country_code in enumerate(country_codes):
        if index < start_index:
            continue
        data = _get(session, f"/Holidays/{quote(country_code, safe='')}/Next")
        if data:
            yield _with_holiday_id(data)
        resumable_source_manager.save_state(NagerDateResumeConfig(index=index + 1))


def _public_holidays_rows(
    session: requests.Session,
    country_codes: list[str],
    resumable_source_manager: ResumableSourceManager[NagerDateResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    work_items = [(country_code, year) for country_code in country_codes for year in _holiday_years()]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = resume.index if resume is not None else 0

    for index, (country_code, year) in enumerate(work_items):
        if index < start_index:
            continue
        data = _get(session, f"/Holidays/{quote(country_code, safe='')}/{year}")
        if data:
            yield _with_holiday_id(data)
        resumable_source_manager.save_state(NagerDateResumeConfig(index=index + 1))


def nager_date_source(
    endpoint: str,
    country_codes: list[str],
    resumable_source_manager: ResumableSourceManager[NagerDateResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session()

    if endpoint == COUNTRIES:
        yield from _countries_rows(session)
        return

    codes_error = check_country_codes(country_codes)
    if codes_error:
        raise ValueError(f"Nager.Date source misconfigured: {codes_error}")

    if endpoint == COUNTRY_INFO:
        yield from _country_info_rows(session, country_codes, resumable_source_manager)
    elif endpoint == NEXT_PUBLIC_HOLIDAYS:
        yield from _next_public_holidays_rows(session, country_codes, resumable_source_manager)
    elif endpoint == PUBLIC_HOLIDAYS:
        yield from _public_holidays_rows(session, country_codes, resumable_source_manager)
    else:
        raise ValueError(f"Unknown Nager.Date endpoint: {endpoint}")

    # Walked to completion: drop the checkpoint so a later attempt restarts cleanly instead of
    # resuming past the end and syncing nothing.
    resumable_source_manager.clear_state()


def validate_credentials(country_codes: list[str]) -> tuple[bool, Optional[str]]:
    """Confirm the API is reachable and the first configured country code is recognized.

    The API is fully open, so there's no credential to check beyond that the configured codes are
    well-formed and real.
    """
    codes_error = check_country_codes(country_codes)
    if codes_error:
        return False, codes_error

    try:
        response = make_tracked_session().get(
            f"{BASE_URL}/Countries/{quote(country_codes[0], safe='')}", timeout=REQUEST_TIMEOUT_SECONDS
        )
    except Exception:
        return False, "Could not reach the Nager.Date API. Please try again."

    if response.status_code == 404:
        return False, f"'{country_codes[0]}' is not a recognized country code."
    if response.status_code != 200:
        return False, "The Nager.Date API returned an unexpected status code. Please try again."

    return True, None
