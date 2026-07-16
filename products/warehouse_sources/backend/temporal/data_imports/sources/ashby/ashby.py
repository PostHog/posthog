import dataclasses
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.ashby.settings import ASHBY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

ASHBY_BASE_URL = "https://api.ashbyhq.com"
PAGE_SIZE = 100  # Ashby's documented max (and default).
# Cheap endpoint to confirm a key is genuine when no specific schema is being validated.
DEFAULT_PROBE_PATH = "department.list"

AUTH_ERROR_HINT = "Ashby API authentication or permission error"


class AshbyAPIError(Exception):
    pass


@dataclasses.dataclass
class AshbyResumeConfig:
    cursor: str


def _headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "Accept": "application/json"}


def _classify_failure_message(errors: list[Any]) -> tuple[bool, str]:
    """Return ``(is_auth_related, joined_message)`` for an ``success: false`` payload.

    Ashby reports many failures as HTTP 200 with ``success: false`` and an ``errors`` array,
    so we sniff the messages to decide whether it's an unrecoverable auth/permission problem.
    """
    message = "; ".join(str(e) for e in errors) or "unknown error"
    lowered = message.lower()
    is_auth = any(
        hint in lowered
        for hint in ("unauthorized", "not authorized", "invalid api key", "permission", "forbidden", "authentication")
    )
    return is_auth, message


def _errors_from_payload(data: dict[str, Any]) -> list[Any]:
    errors = data.get("errors")
    if errors:
        return errors if isinstance(errors, list) else [errors]
    if data.get("error"):
        return [data["error"]]
    return []


class AshbyCursorPaginator(JSONResponseCursorPaginator):
    """Cursor-in-JSON-body pagination plus Ashby's HTTP-200 error envelope.

    Ashby reports many failures as HTTP 200 with ``success: false`` and an ``errors``
    array — raise on those (auth-ish messages carry ``AUTH_ERROR_HINT`` so the job-level
    classifier treats them as non-retryable). Termination honors ``moreDataAvailable``,
    which can be false even when a ``nextCursor`` is present.
    """

    def __init__(self, path: str) -> None:
        super().__init__(cursor_path="nextCursor", cursor_param="cursor", param_location="json")
        self._path = path

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        payload = response.json()
        if not payload.get("success", False):
            is_auth, message = _classify_failure_message(_errors_from_payload(payload))
            if is_auth:
                raise AshbyAPIError(f"{AUTH_ERROR_HINT} for path {self._path}: {message}")
            raise AshbyAPIError(f"Ashby API error for path {self._path}: {message}")

        super().update_state(response, data)
        if not payload.get("moreDataAvailable", False):
            self._has_next_page = False


def ashby_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AshbyResumeConfig],
) -> SourceResponse:
    config = ASHBY_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": ASHBY_BASE_URL,
            "headers": _headers(),
            # Ashby uses HTTP Basic auth: API key as username, empty password.
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
            "paginator": AshbyCursorPaginator(config.path),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "method": "post",
                    "json": {"limit": PAGE_SIZE},
                    "data_selector": "results",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the checkpoint fires AFTER a page is yielded so a
        # crash re-fetches from the next page (already-yielded pages are persisted); merge/replace
        # dedupes on the primary key.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(AshbyResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every Ashby endpoint is full refresh
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_key,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def check_access(api_key: str, path: str) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate credentials.

    Ashby's RPC endpoints are POST-only and report many failures as HTTP 200 with
    ``success: false``, so the generic GET-based ``validate_via_probe`` can't express this
    check. Returns a normalized ``(status, message)`` where status mimics HTTP semantics:
      200 = reachable, 401 = bad key, 403 = valid key without scope, other = unexpected.
    """
    session = make_tracked_session(redact_values=(api_key,))
    try:
        response = session.post(
            f"{ASHBY_BASE_URL}/{path}", json={"limit": 1}, auth=(api_key, ""), headers=_headers(), timeout=15
        )
    except Exception as e:
        return 0, f"Could not connect to Ashby: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Ashby returned HTTP {response.status_code}"

    try:
        data = response.json()
    except ValueError:
        # A 200 that isn't JSON (e.g. a proxy/maintenance HTML page) is not a valid Ashby
        # response — fail validation rather than reporting the credentials as good.
        return 0, "Ashby returned a non-JSON response"

    if data.get("success", False):
        return 200, None

    is_auth, message = _classify_failure_message(_errors_from_payload(data))
    if is_auth:
        # Can't distinguish bad-key from missing-scope purely from the message; treat as 403
        # (valid key, insufficient scope) so source-create accepts keys scoped to a subset of
        # endpoints. A genuinely invalid key surfaces as HTTP 401 above.
        return 403, message
    return 400, message
