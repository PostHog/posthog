import re
import json
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.settings import (
    COCKPIT_PRIMARY_KEYS,
    CTA_CONFIGURATION,
    CTA_OBJECT_NAME,
    CTA_TASK,
    DATE_DATA_TYPES,
    DESCRIBE_PATH,
    ENDPOINTS,
    GAINSIGHT_CS_OBJECTS,
    GSID,
    MAX_PAGE_SIZE,
    OBJECT_NAME_PATTERN,
    PICKLIST_CATEGORIES,
    PICKLIST_ENTITY_TYPE,
    PICKLIST_PATH,
    QUERY_PATH,
    TASK_CTA_ID,
    TASK_LIST_PATH,
    TASK_PAGE_SIZE,
)

REQUEST_TIMEOUT = 60
CREATED_DATE = "CreatedDate"

# The host is customer-controlled, so a body is never buffered unbounded (size cap) nor allowed to
# hold a worker by dribbling bytes under the per-read timeout (time cap).
MAX_RESPONSE_BYTES = 128 * 1024 * 1024
MAX_DOWNLOAD_SECONDS = 120
RESPONSE_CHUNK_BYTES = 256 * 1024
# Pages one attempt walks before it checkpoints and stops. Temporal retries the activity, which
# resumes from the saved offset, so a large object still finishes while a host that never sends a
# short page can't hold the worker for the whole activity timeout.
MAX_PAGES_PER_ATTEMPT = 2000
# Task pages read for one CTA before the source gives up on a host that never sends a short page.
MAX_TASK_PAGES_PER_CTA = 100

HOST_NOT_ALLOWED_ERROR = "That Gainsight domain isn't allowed."
RESPONSE_TOO_LARGE_ERROR = "Gainsight returned a response larger than this source accepts."
RESPONSE_TOO_SLOW_ERROR = "Gainsight took too long to send a response."

_DOMAIN_RE = re.compile(r"^[A-Za-z0-9.\-]+$")
_OBJECT_NAME_RE = re.compile(OBJECT_NAME_PATTERN)


class GainsightCsHostNotAllowedError(Exception):
    pass


class GainsightCsResponseTooLargeError(Exception):
    pass


class GainsightCsResponseTooSlowError(Exception):
    pass


class GainsightCsPageBudgetExhaustedError(Exception):
    pass


def _read_capped_json(response: requests.Response) -> Any:
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    try:
        for chunk in response.iter_content(chunk_size=RESPONSE_CHUNK_BYTES):
            if time.monotonic() > deadline:
                raise GainsightCsResponseTooSlowError(RESPONSE_TOO_SLOW_ERROR)
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise GainsightCsResponseTooLargeError(RESPONSE_TOO_LARGE_ERROR)
            chunks.append(chunk)
    finally:
        response.close()
    return json.loads(b"".join(chunks) or b"null")


@frozen
class GainsightCsResumeConfig:
    # Row index of the next page to request. The Read API pages with limit/offset in the POST body,
    # so an offset is all that's needed to pick a sync back up.
    offset: int = 0
    # cta_task only: the first task page to request for the CTA at `offset`.
    task_page: int = 1


@frozen
class GainsightCsField:
    name: str
    data_type: str
    sortable: bool


def normalize_domain(domain: str) -> str:
    """Turn whatever the user typed into a bare Gainsight tenant host.

    Accepts ``acme.gainsightcloud.com``, ``https://acme.gainsightcloud.com/``, or
    ``acme.gainsightcloud.com/v1`` and returns ``acme.gainsightcloud.com``.
    """
    domain = domain.strip()
    domain = re.sub(r"^https?://", "", domain, flags=re.IGNORECASE)
    domain = domain.split("/")[0]
    return domain.strip().rstrip("/")


def _base_url(domain: str) -> str:
    return f"https://{normalize_domain(domain)}"


def _headers(access_key: str) -> dict[str, str]:
    return {
        "accesskey": access_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def check_domain(domain: str, team_id: Optional[int]) -> tuple[bool, Optional[str]]:
    normalized = normalize_domain(domain)
    if not normalized or not _DOMAIN_RE.match(normalized):
        return (
            False,
            "That doesn't look like a Gainsight domain. Enter the host you reach Gainsight on, e.g. 'acme.gainsightcloud.com'.",
        )

    # Gainsight tenants can sit on a customer-mapped custom domain, so the host can't be pinned to a
    # known suffix — block anything resolving to a private/internal address instead (SSRF). Only
    # enforced on cloud; see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(normalized, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    return True, None


def _require_allowed_host(domain: str, team_id: Optional[int]) -> None:
    ok, err = check_domain(domain, team_id)
    if not ok:
        raise GainsightCsHostNotAllowedError(err or HOST_NOT_ALLOWED_ERROR)


def resolve_object_name(schema_name: str, custom_objects: Optional[str]) -> str:
    known = GAINSIGHT_CS_OBJECTS.get(schema_name)
    if known is not None:
        return known.object_name

    if schema_name == CTA_TASK:
        # Tasks are listed per CTA, so reading them starts with a query over the CTA object.
        return CTA_OBJECT_NAME

    if schema_name in parse_custom_objects(custom_objects):
        return schema_name

    raise ValueError(f"Unknown Gainsight object '{schema_name}'.")


def parse_custom_objects(custom_objects: Optional[str]) -> list[str]:
    """Split the comma-separated custom-object field into validated object names.

    Values land in the request path, so anything that isn't shaped like a Gainsight object name is
    dropped rather than sent.
    """
    if not custom_objects:
        return []

    names = []
    for raw in custom_objects.split(","):
        name = raw.strip()
        if name and _OBJECT_NAME_RE.match(name) and name not in ENDPOINTS:
            names.append(name)
    return names


def _envelope_data(body: Any, object_name: str) -> Any:
    """Unwrap Gainsight's shared response envelope, raising on an API-level failure.

    Every endpoint answers 200 with ``{"result": true|false, "errorDesc": ..., "data": ...}``, so a
    failure that arrives on a 200 has to be read out of the body or it looks like an empty sync.
    """
    if not isinstance(body, dict):
        raise ValueError(f"Gainsight returned an unexpected response for '{object_name}'.")

    if body.get("result") is False:
        detail = body.get("errorDesc") or body.get("message") or body.get("errorCode") or "unknown error"
        raise ValueError(f"Gainsight rejected the request for '{object_name}': {detail}")

    return body.get("data")


def _rows_from_body(body: Any, object_name: str) -> list[dict[str, Any]]:
    """Pull the record list out of a Read API response.

    The envelope is not consistent across objects: the Company docs show ``data`` as the record
    array, while the Timeline docs show the records nested under ``data.records``. Both shapes are
    accepted, and anything else raises — wrapping a stray object as a single row would quietly seed
    a junk record into the customer's table.
    """
    data = _envelope_data(body, object_name)

    if data is None:
        return []
    if isinstance(data, dict) and "records" in data:
        data = data.get("records") or []
    if not isinstance(data, list):
        raise ValueError(f"Gainsight returned an unexpected record shape for '{object_name}'.")

    return [row for row in data if isinstance(row, dict)]


def _parse_fields(body: Any, object_name: str) -> list[GainsightCsField]:
    data = _envelope_data(body, object_name)

    raw_definitions = data if isinstance(data, list) else [data]
    definitions = [d for d in raw_definitions if isinstance(d, dict)]
    # Describe answers with a list of object definitions even when one object was asked for. Take the
    # entry naming the object we requested; only when none does — a response carrying a single
    # unlabelled definition — fall back to scanning them, so another object's fields can never stand
    # in for the one being synced.
    matching = [d for d in definitions if str(d.get("objectName", "")).lower() == object_name.lower()]

    for definition in matching or definitions:
        fields = []
        for raw in definition.get("fields") or []:
            name = raw.get("fieldName")
            if not name:
                continue
            meta = raw.get("meta") or {}
            fields.append(
                GainsightCsField(
                    name=name,
                    data_type=str(raw.get("dataType") or "").upper(),
                    sortable=bool(meta.get("sortable")),
                )
            )
        if fields:
            return fields

    raise ValueError(
        f"Gainsight returned no fields for object '{object_name}'. Check the object name on the "
        "Data Management page and that the access key can read it."
    )


def _picklist_rows(body: Any) -> list[dict[str, Any]]:
    """Flatten the picklist response, which keys each category's values by category name."""
    data = _envelope_data(body, CTA_CONFIGURATION)

    if data is None:
        return []
    if not isinstance(data, dict):
        raise ValueError(f"Gainsight returned an unexpected record shape for '{CTA_CONFIGURATION}'.")

    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for category, values in data.items():
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict) or not value.get("gsid"):
                continue
            row = {**value, "picklistCategory": value.get("picklistCategory") or category}
            rows.setdefault((row["picklistCategory"], row["gsid"]), row)
    return list(rows.values())


def _get_json(session: requests.Session, url: str, access_key: str, params: Optional[dict[str, Any]] = None) -> Any:
    response = session.get(url, headers=_headers(access_key), params=params, timeout=REQUEST_TIMEOUT, stream=True)
    _raise_for_redirect(response)
    response.raise_for_status()
    return _read_capped_json(response)


def _post_json(session: requests.Session, url: str, access_key: str, body: dict[str, Any]) -> Any:
    response = session.post(url, headers=_headers(access_key), json=body, timeout=REQUEST_TIMEOUT, stream=True)
    _raise_for_redirect(response)
    response.raise_for_status()
    return _read_capped_json(response)


def describe_object(
    session: requests.Session, domain: str, access_key: str, object_name: str
) -> list[GainsightCsField]:
    """Fetch an object's field list.

    The Read API has no "select all" — every field to return has to be named in the request — and
    each tenant's objects carry their own custom fields, so the field list is discovered per sync
    rather than hardcoded.
    """
    url = f"{_base_url(domain)}{DESCRIBE_PATH.format(object_name=object_name)}"
    return _parse_fields(_get_json(session, url, access_key), object_name)


def _gsid_order_by(fields: list[GainsightCsField]) -> Optional[dict[str, str]]:
    # Paginating with limit/offset over an unordered result set can skip or repeat rows as records
    # shift between calls, so order on Gsid when the object reports it as sortable.
    return {GSID: "asc"} if any(field.name == GSID and field.sortable for field in fields) else None


def _raise_for_redirect(response: requests.Response) -> None:
    # The session is built with allow_redirects=False so a 3xx can't replay the access key to
    # whatever host the redirect names, which would sidestep the host check.
    if response.is_redirect or response.is_permanent_redirect:
        raise GainsightCsHostNotAllowedError(HOST_NOT_ALLOWED_ERROR)


def _to_datetime(value: Any) -> Any:
    """Convert Gainsight's epoch-millisecond date values into real datetimes.

    Date and datetime fields come back as epoch milliseconds, which would otherwise land as a bare
    integer column. ISO strings are returned by some endpoints and pass through untouched.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return value
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return value


def _normalize_row(row: dict[str, Any], date_fields: frozenset[str]) -> dict[str, Any]:
    if not date_fields:
        return row
    return {key: _to_datetime(value) if key in date_fields else value for key, value in row.items()}


def gainsight_cs_source(
    domain: str,
    access_key: str,
    schema_name: str,
    object_name: str,
    primary_keys: list[str],
    team_id: int,
    resumable_source_manager: ResumableSourceManager[GainsightCsResumeConfig],
) -> SourceResponse:
    _require_allowed_host(domain, team_id)

    session = make_tracked_session(redact_values=(access_key,), allow_redirects=False)
    fields = describe_object(session, domain, access_key, object_name)

    select = [field.name for field in fields]
    date_fields = frozenset(field.name for field in fields if field.data_type in DATE_DATA_TYPES)
    field_names = {field.name for field in fields}
    order_by = _gsid_order_by(fields)

    url = f"{_base_url(domain)}{QUERY_PATH.format(object_name=object_name)}"

    def items() -> Iterator[list[dict[str, Any]]]:
        # Re-checked here as well as at setup: the domain may have been edited, or now resolve to an
        # internal address (DNS rebinding), since the source was created.
        _require_allowed_host(domain, team_id)

        offset = 0
        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None:
                offset = max(resume.offset, 0)

        for _ in range(MAX_PAGES_PER_ATTEMPT):
            body: dict[str, Any] = {"select": select, "limit": MAX_PAGE_SIZE, "offset": offset}
            if order_by is not None:
                body["orderBy"] = order_by

            rows = _rows_from_body(_post_json(session, url, access_key, body), object_name)
            if rows:
                yield [_normalize_row(row, date_fields) for row in rows]

            # A short page means the API ran out of records; advancing by the rows actually returned
            # (rather than by the requested limit) keeps the cursor honest if it ever returns fewer.
            if len(rows) < MAX_PAGE_SIZE:
                # A finished walk must not leave its offset behind: within the checkpoint TTL the
                # next job would resume there and merge instead of replacing the table.
                resumable_source_manager.clear_state()
                return

            offset += len(rows)
            # Saved after the page is yielded, so a crash re-reads the last page — which the merge
            # dedupes on the primary key — instead of stepping over it.
            resumable_source_manager.save_state(GainsightCsResumeConfig(offset=offset))

        # A safe point keeps the cursor saved after the last yield. The source holds no rows here.
        resumable_source_manager.safe_point()
        raise GainsightCsPageBudgetExhaustedError(
            f"Stopped after {MAX_PAGES_PER_ATTEMPT} pages of '{object_name}'; the next attempt resumes at offset {offset}."
        )

    partition_keys = [CREATED_DATE] if CREATED_DATE in field_names else None

    return SourceResponse(
        name=schema_name,
        items=items,
        primary_keys=primary_keys,
        partition_mode="datetime" if partition_keys else None,
        partition_format="month" if partition_keys else None,
        partition_keys=partition_keys,
    )


def gainsight_cs_cta_configuration_source(domain: str, access_key: str, team_id: int) -> SourceResponse:
    _require_allowed_host(domain, team_id)

    session = make_tracked_session(redact_values=(access_key,), allow_redirects=False)
    url = f"{_base_url(domain)}{PICKLIST_PATH}"
    params = {"category": ",".join(PICKLIST_CATEGORIES), "et": PICKLIST_ENTITY_TYPE}

    def items() -> Iterator[list[dict[str, Any]]]:
        _require_allowed_host(domain, team_id)
        rows = _picklist_rows(_get_json(session, url, access_key, params))
        if rows:
            yield rows

    return SourceResponse(
        name=CTA_CONFIGURATION,
        items=items,
        primary_keys=COCKPIT_PRIMARY_KEYS[CTA_CONFIGURATION],
    )


def gainsight_cs_cta_task_source(
    domain: str,
    access_key: str,
    team_id: int,
    resumable_source_manager: ResumableSourceManager[GainsightCsResumeConfig],
) -> SourceResponse:
    _require_allowed_host(domain, team_id)

    session = make_tracked_session(redact_values=(access_key,), allow_redirects=False)
    order_by = _gsid_order_by(describe_object(session, domain, access_key, CTA_OBJECT_NAME))
    query_url = f"{_base_url(domain)}{QUERY_PATH.format(object_name=CTA_OBJECT_NAME)}"

    def cta_task_pages(cta_gsid: str, cta_offset: int, first_page: int) -> Iterator[list[dict[str, Any]]]:
        url = f"{_base_url(domain)}{TASK_LIST_PATH.format(cta_gsid=cta_gsid)}"
        for page_number in range(first_page, first_page + MAX_TASK_PAGES_PER_CTA):
            params = {"pn": page_number, "ps": TASK_PAGE_SIZE}
            rows = _rows_from_body(_get_json(session, url, access_key, params), CTA_TASK)
            last_page = len(rows) < TASK_PAGE_SIZE
            if last_page:
                next_state = GainsightCsResumeConfig(offset=cta_offset + 1)
            else:
                next_state = GainsightCsResumeConfig(offset=cta_offset, task_page=page_number + 1)
            resumable_source_manager.save_state(next_state)
            if rows:
                yield [{**row, TASK_CTA_ID: cta_gsid} for row in rows]
            else:
                resumable_source_manager.safe_point()
            if last_page:
                return

        # The staged cursor points at the next task page, so the next attempt continues this CTA.
        resumable_source_manager.safe_point()
        raise GainsightCsPageBudgetExhaustedError(
            f"Stopped after {MAX_TASK_PAGES_PER_CTA} task pages of CTA '{cta_gsid}'; the next attempt resumes at page {page_number + 1}."
        )

    def items() -> Iterator[list[dict[str, Any]]]:
        _require_allowed_host(domain, team_id)

        # The offset counts CTAs, not tasks: it is the index of the CTA whose tasks to fetch next.
        offset = 0
        first_task_page = 1
        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None:
                offset = max(resume.offset, 0)
                first_task_page = max(resume.task_page, 1)

        for _ in range(MAX_PAGES_PER_ATTEMPT):
            body: dict[str, Any] = {"select": [GSID], "limit": MAX_PAGE_SIZE, "offset": offset}
            if order_by is not None:
                body["orderBy"] = order_by

            ctas = _rows_from_body(_post_json(session, query_url, access_key, body), CTA_OBJECT_NAME)
            for cta in ctas:
                cta_gsid = cta.get(GSID)
                # The Gsid lands in the request path, so only an id-shaped value is sent.
                if isinstance(cta_gsid, str) and _OBJECT_NAME_RE.match(cta_gsid):
                    yield from cta_task_pages(cta_gsid, offset, first_task_page)
                offset += 1
                first_task_page = 1

            if len(ctas) < MAX_PAGE_SIZE:
                return

        resumable_source_manager.safe_point()
        raise GainsightCsPageBudgetExhaustedError(
            f"Stopped after {MAX_PAGES_PER_ATTEMPT} pages of '{CTA_OBJECT_NAME}'; the next attempt resumes at CTA {offset}."
        )

    return SourceResponse(
        name=CTA_TASK,
        items=items,
        primary_keys=COCKPIT_PRIMARY_KEYS[CTA_TASK],
        # Cleared only once the pipeline has written every batch, so a failed final write resumes
        # near the end of the fan-out instead of starting it again.
        on_complete=resumable_source_manager.clear_state,
    )


def _probe(
    domain: str,
    access_key: str,
    team_id: Optional[int],
    path: str,
    not_found_error: str,
    parse: Callable[[Any], object],
) -> tuple[bool, Optional[str]]:
    ok, err = check_domain(domain, team_id)
    if not ok:
        return False, err

    url = f"{_base_url(domain)}{path}"
    try:
        response = make_tracked_session(redact_values=(access_key,), allow_redirects=False).get(
            url, headers=_headers(access_key), timeout=30, stream=True
        )
    except requests.exceptions.RequestException as e:
        return False, f"Could not reach Gainsight ({e}). Check the domain and your network."

    if response.is_redirect or response.is_permanent_redirect:
        response.close()
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code in (401, 403):
        response.close()
        return (
            False,
            "Gainsight rejected the access key. Generate one under Administration → Connectors in "
            "Gainsight, then reconnect.",
        )

    if response.status_code == 404:
        response.close()
        return False, not_found_error

    if response.status_code != 200:
        response.close()
        return False, f"Gainsight returned an unexpected status ({response.status_code})."

    try:
        parse(_read_capped_json(response))
    except (ValueError, GainsightCsResponseTooLargeError, GainsightCsResponseTooSlowError) as e:
        return False, str(e)

    return True, None


def validate_credentials(
    domain: str, access_key: str, object_name: str, team_id: Optional[int]
) -> tuple[bool, Optional[str]]:
    return _probe(
        domain,
        access_key,
        team_id,
        DESCRIBE_PATH.format(object_name=object_name),
        f"Gainsight has no object named '{object_name}' on that domain.",
        lambda body: _parse_fields(body, object_name),
    )


def validate_cta_configuration_access(
    domain: str, access_key: str, team_id: Optional[int]
) -> tuple[bool, Optional[str]]:
    query = urlencode({"category": ",".join(PICKLIST_CATEGORIES), "et": PICKLIST_ENTITY_TYPE})
    return _probe(
        domain,
        access_key,
        team_id,
        f"{PICKLIST_PATH}?{query}",
        "Gainsight didn't find the Cockpit configuration API on that domain.",
        _picklist_rows,
    )
