import re
import dataclasses
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlsplit

from requests import Request, Response

from products.warehouse_sources.sources.deputy.settings import (
    API_VERSION,
    CREATED_FIELD,
    DEPUTY_ENDPOINTS,
    MODIFIED_FIELD,
    PAGE_SIZE,
    PRIMARY_KEY,
)
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)

# One or two DNS labels in front of deputy.com, for example `acme.au.deputy.com` or
# `usdemo.ent-na.deputy.com`. The pattern rejects ports, user info and any host outside deputy.com,
# so the token is never sent to a host that a user typed in.
_INSTALL_HOST_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.){1,2}deputy\.com$")
_DEPUTY_SUFFIX = ".deputy.com"

# The watermark is a UTC timestamp, but a Deputy install runs in its own time zone. If Deputy reads
# the filter value in local time, it can sit up to 14 hours late (UTC+14). Starting 14 hours early
# re-reads some rows, which the merge on `Id` deduplicates, and never skips a row.
_TIMEZONE_SAFETY_WINDOW = timedelta(hours=14)


class InvalidDeputyInstallError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class DeputyResumeConfig:
    # The field the run sorts and pages on: `Id` for a full refresh, `Modified` for an incremental sync.
    field: str
    # The lower bound of the next request. Rows with a value below it were all read.
    value: Any
    # The number of rows at exactly `value` that the run already read.
    skip: int = 0


def normalize_install_host(install_url: str) -> str:
    """Return the Deputy install host, such as `acme.au.deputy.com`, or raise for any other host."""
    raw = (install_url or "").strip().lower()
    if not raw:
        raise InvalidDeputyInstallError("Enter your Deputy URL.")
    if "://" not in raw:
        raw = f"https://{raw}"

    parts = urlsplit(raw)
    host = parts.netloc
    if parts.scheme not in ("http", "https") or not host:
        raise InvalidDeputyInstallError(f"Invalid Deputy URL: {install_url!r}")
    if not host.endswith(_DEPUTY_SUFFIX):
        host = f"{host}{_DEPUTY_SUFFIX}"
    if not _INSTALL_HOST_RE.match(host):
        raise InvalidDeputyInstallError(
            f"Invalid Deputy URL: {install_url!r}. Use the address of your Deputy install, "
            "for example https://yourbusiness.au.deputy.com."
        )
    return host


def base_url(install_url: str) -> str:
    return f"https://{normalize_install_host(install_url)}/api/{API_VERSION}"


def format_modified_since(value: Any) -> str:
    """Format the incremental watermark as an ISO 8601 timestamp for a `Modified` search."""
    if isinstance(value, datetime):
        moment = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    elif isinstance(value, date):
        moment = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return str(value)
    return (moment - _TIMEZONE_SAFETY_WINDOW).isoformat(timespec="seconds")


class DeputyQueryPaginator(BasePaginator):
    """Keyset pagination for the Resource API QUERY call.

    Each request sorts ascending on one field and asks for the rows at or above the last value read.
    The `start` offset skips only the rows at exactly that value that were already read, so a row that
    changes during the run moves the rows behind it without skipping any of them.
    """

    def __init__(self, field: str, value: Any = None, skip: int = 0, page_size: int = PAGE_SIZE) -> None:
        super().__init__()
        self.field = field
        self.page_size = page_size
        self._value = value
        self._skip = skip

    def _apply(self, request: Request) -> None:
        body: dict[str, Any] = {"sort": {self.field: "asc"}, "start": self._skip, "max": self.page_size}
        if self._value is not None:
            body["search"] = {"s1": {"field": self.field, "type": "ge", "data": self._value}}
        request.json = body

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        rows = data or []
        if len(rows) < self.page_size:
            self._has_next_page = False
            return

        last_value = rows[-1].get(self.field) if isinstance(rows[-1], dict) else None
        if last_value is None or last_value == "":
            raise ValueError(f"Deputy returned a row without {self.field}, so the next page can't be requested")

        ties = 0
        for row in reversed(rows):
            if not isinstance(row, dict) or row.get(self.field) != last_value:
                break
            ties += 1

        if last_value == self._value:
            self._skip += ties
        else:
            self._value = last_value
            self._skip = ties
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if not self._has_next_page or self._value is None:
            return None
        return {"field": self.field, "value": self._value, "skip": self._skip}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        if state.get("field") == self.field and state.get("value") is not None:
            self._value = state["value"]
            self._skip = int(state.get("skip") or 0)
            self._has_next_page = True


def deputy_source(
    install_url: str,
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DeputyResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    endpoint_config = DEPUTY_ENDPOINTS[endpoint]

    if should_use_incremental_field:
        sort_field = MODIFIED_FIELD
        start_value = (
            format_modified_since(db_incremental_field_last_value)
            if db_incremental_field_last_value is not None
            else None
        )
    else:
        sort_field = PRIMARY_KEY
        start_value = None

    config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(install_url),
            "auth": {"type": "bearer", "token": access_token},
            "headers": {"Accept": "application/json"},
            "paginator": DeputyQueryPaginator(field=sort_field, value=start_value),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "write_disposition": {"disposition": "merge", "strategy": "upsert"}
                if should_use_incremental_field
                else "replace",
                "endpoint": {
                    "method": "POST",
                    "path": f"/resource/{endpoint_config.resource}/QUERY",
                    # QUERY returns a bare JSON array. An object body on a 200 means the response
                    # shape changed, so fail the run instead of writing the object as a row.
                    "data_selector_required": True,
                },
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            # The paginator ignores a cursor that a run in the other sync mode saved.
            initial_paginator_state = dataclasses.asdict(resume)

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("value") is not None:
            resumable_source_manager.save_state(
                DeputyResumeConfig(field=state["field"], value=state["value"], skip=int(state.get("skip") or 0))
            )

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[PRIMARY_KEY],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[CREATED_FIELD],
        # Only the incremental read sorts on `Modified`. A full refresh sorts on `Id`.
        sort_mode="asc" if should_use_incremental_field else None,
    )


def validate_credentials(install_url: str, access_token: str) -> tuple[bool, str | None]:
    try:
        url = f"{base_url(install_url)}/me"
    except InvalidDeputyInstallError as error:
        return False, str(error)

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,)),
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        # The token rides in a header, so do not follow a redirect to another host.
        allow_redirects=False,
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Deputy rejected the permanent token. Create a new token in your Deputy install, then try again."
    if status is None:
        return False, "Could not connect to your Deputy install. Check the Deputy URL, then try again."
    return False, f"Deputy returned an unexpected status ({status}). Check the Deputy URL and token, then try again."
