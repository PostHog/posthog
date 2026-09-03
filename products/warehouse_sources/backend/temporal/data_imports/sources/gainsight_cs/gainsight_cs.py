import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.settings import (
    DATE_DATA_TYPES,
    DESCRIBE_PATH,
    GAINSIGHT_CS_OBJECTS,
    GSID,
    MAX_PAGE_SIZE,
    OBJECT_NAME_PATTERN,
    QUERY_PATH,
)

REQUEST_TIMEOUT = 60
CREATED_DATE = "CreatedDate"

HOST_NOT_ALLOWED_ERROR = "That Gainsight domain isn't allowed."

_DOMAIN_RE = re.compile(r"^[A-Za-z0-9.\-]+$")
_OBJECT_NAME_RE = re.compile(OBJECT_NAME_PATTERN)


class GainsightCsHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class GainsightCsResumeConfig:
    # Row index of the next page to request. The Read API pages with limit/offset in the POST body,
    # so an offset is all that's needed to pick a sync back up.
    offset: int = 0


@dataclasses.dataclass(frozen=True)
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
        if name and _OBJECT_NAME_RE.match(name) and name not in GAINSIGHT_CS_OBJECTS:
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


def describe_object(
    session: requests.Session, domain: str, access_key: str, object_name: str
) -> list[GainsightCsField]:
    """Fetch an object's field list.

    The Read API has no "select all" — every field to return has to be named in the request — and
    each tenant's objects carry their own custom fields, so the field list is discovered per sync
    rather than hardcoded.
    """
    url = f"{_base_url(domain)}{DESCRIBE_PATH.format(object_name=object_name)}"
    response = session.get(url, headers=_headers(access_key), timeout=REQUEST_TIMEOUT)
    _raise_for_redirect(response)
    response.raise_for_status()
    return _parse_fields(response.json(), object_name)


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
    # Paginating with limit/offset over an unordered result set can skip or repeat rows as records
    # shift between calls, so order on Gsid when the object reports it as sortable.
    order_by = {GSID: "asc"} if any(field.name == GSID and field.sortable for field in fields) else None

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

        while True:
            body: dict[str, Any] = {"select": select, "limit": MAX_PAGE_SIZE, "offset": offset}
            if order_by is not None:
                body["orderBy"] = order_by

            response = session.post(url, headers=_headers(access_key), json=body, timeout=REQUEST_TIMEOUT)
            _raise_for_redirect(response)
            response.raise_for_status()

            rows = _rows_from_body(response.json(), object_name)
            if rows:
                yield [_normalize_row(row, date_fields) for row in rows]

            # A short page means the API ran out of records; advancing by the rows actually returned
            # (rather than by the requested limit) keeps the cursor honest if it ever returns fewer.
            if len(rows) < MAX_PAGE_SIZE:
                break

            offset += len(rows)
            # Saved after the page is yielded, so a crash re-reads the last page — which the merge
            # dedupes on the primary key — instead of stepping over it.
            resumable_source_manager.save_state(GainsightCsResumeConfig(offset=offset))

    partition_keys = [CREATED_DATE] if CREATED_DATE in field_names else None

    return SourceResponse(
        name=schema_name,
        items=items,
        primary_keys=primary_keys,
        partition_mode="datetime" if partition_keys else None,
        partition_format="month" if partition_keys else None,
        partition_keys=partition_keys,
    )


def validate_credentials(
    domain: str, access_key: str, object_name: str, team_id: Optional[int]
) -> tuple[bool, Optional[str]]:
    ok, err = check_domain(domain, team_id)
    if not ok:
        return False, err

    url = f"{_base_url(domain)}{DESCRIBE_PATH.format(object_name=object_name)}"
    try:
        response = make_tracked_session(redact_values=(access_key,), allow_redirects=False).get(
            url, headers=_headers(access_key), timeout=30
        )
    except requests.exceptions.RequestException as e:
        return False, f"Could not reach Gainsight ({e}). Check the domain and your network."

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code in (401, 403):
        return (
            False,
            "Gainsight rejected the access key. Generate one under Administration → Connectors in "
            "Gainsight, then reconnect.",
        )

    if response.status_code == 404:
        return False, f"Gainsight has no object named '{object_name}' on that domain."

    if response.status_code != 200:
        return False, f"Gainsight returned an unexpected status ({response.status_code})."

    try:
        _parse_fields(response.json(), object_name)
    except ValueError as e:
        return False, str(e)

    return True, None
