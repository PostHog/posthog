import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import OAuth2Auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.settings import (
    CULTURE_AMP_BASE_URL,
    CULTURE_AMP_ENDPOINTS,
    CULTURE_AMP_TOKEN_URL,
)

# Fan-out parent resource name. With include_from_parent=["id"] the framework injects the parent
# employee id into demographic rows as `_employees_id`; a data_map renames it to the `_employee_id`
# key the rows carried before the rest_source migration.
_EMPLOYEES_PARENT = "employees"
_PARENT_EMPLOYEE_ID_KEY = f"_{_EMPLOYEES_PARENT}_id"
_EMPLOYEE_ID_KEY = "_employee_id"
_DEMOGRAPHICS_CHILD_PATH = "employees/{employee_id}/demographics"

# Scope minted for the create-time credential probe: enough to list employees.
_VALIDATE_SCOPES = "employees-read"


@dataclasses.dataclass
class CultureAmpResumeConfig:
    # Pre-framework fields, kept so previously saved state still parses (dataclass(**saved)).
    # Cursor endpoints: the afterKey of the next unfetched page.
    cursor: Optional[str] = None
    # Fan-out: id of the last fully-processed employee (pre-framework shape).
    last_processed_employee_id: Optional[str] = None
    # Framework fan-out checkpoint for employee_demographics
    # ({"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}).
    fanout_state: Optional[dict[str, Any]] = None


def _scoped(account_id: str, scopes: str) -> str:
    """Build the Culture Amp scope string (`target-entity:{account_id}:{scopes}`)."""
    return f"target-entity:{account_id}:{scopes}"


def _make_auth(client_id: str, client_secret: str, account_id: str, scopes: str) -> OAuth2Auth:
    # Culture Amp uses OAuth2 client-credentials; tokens last ~1h and the framework re-mints on
    # expiry mid-run. Scopes are minted per endpoint so credentials granted a subset of permissions
    # can still sync the streams they cover.
    return OAuth2Auth(
        token_url=CULTURE_AMP_TOKEN_URL,
        client_id=client_id,
        client_secret=client_secret,
        grant_type="client_credentials",
        scopes=_scoped(account_id, scopes),
    )


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor for the RFC 3339 after_date filter."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _paginator() -> JSONResponseCursorPaginator:
    # Every Culture Amp list paginates with a `cursor` query param and an `afterKey` under
    # `pagination` in the response body.
    return JSONResponseCursorPaginator(cursor_path="pagination.afterKey", cursor_param="cursor")


def _client_config(auth: OAuth2Auth) -> ClientConfig:
    return {
        "base_url": CULTURE_AMP_BASE_URL,
        "auth": auth,
        "paginator": _paginator(),
    }


def _rename_employee_id(row: dict[str, Any]) -> dict[str, Any]:
    row[_EMPLOYEE_ID_KEY] = row.pop(_PARENT_EMPLOYEE_ID_KEY)
    return row


def _fanout_initial_state(resume: CultureAmpResumeConfig) -> Optional[dict[str, Any]]:
    if resume.fanout_state is not None:
        return resume.fanout_state
    # Pre-framework state saved only the last fully-processed employee id. Translate it into a
    # single completed child path so that employee is skipped on resume; any earlier employees
    # are re-fetched, which is safe (merge dedupes on the [_employee_id, name] primary key).
    if resume.last_processed_employee_id is None:
        return None
    return {
        "completed": [_DEMOGRAPHICS_CHILD_PATH.format(employee_id=resume.last_processed_employee_id)],
        "current": None,
        "child_state": None,
    }


def culture_amp_source(
    client_id: str,
    client_secret: str,
    account_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CultureAmpResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CULTURE_AMP_ENDPOINTS[endpoint]
    auth = _make_auth(client_id, client_secret, account_id, config.scopes)

    resume: Optional[CultureAmpResumeConfig] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()

    if config.per_employee:
        initial_state = _fanout_initial_state(resume) if resume is not None else None

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state is not None:
                resumable_source_manager.save_state(CultureAmpResumeConfig(fanout_state=state))

        rest_config: RESTAPIConfig = {
            "client": _client_config(auth),
            "resources": [
                {
                    "name": _EMPLOYEES_PARENT,
                    "endpoint": {
                        "path": "employees",
                        "data_selector": "data",
                    },
                },
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": _DEMOGRAPHICS_CHILD_PATH,
                        "params": {
                            "employee_id": {
                                "type": "resolve",
                                "resource": _EMPLOYEES_PARENT,
                                "field": "id",
                            },
                        },
                        "data_selector": "data",
                        # Each employee's demographics list is cursor-paged like every other list.
                        "paginator": _paginator(),
                    },
                    "include_from_parent": ["id"],
                    "data_map": _rename_employee_id,
                },
            ],
        }
        resources = {
            res.name: res
            for res in rest_api_resources(
                rest_config,
                team_id,
                job_id,
                None,
                resume_hook=save_fanout_checkpoint,
                initial_paginator_state=initial_state,
            )
        }
        resource = resources[endpoint]
    else:
        params: dict[str, Any] = {}
        if config.incremental_fields and should_use_incremental_field and db_incremental_field_last_value is not None:
            params["after_date"] = _format_timestamp(db_incremental_field_last_value)

        initial_paginator_state: Optional[dict[str, Any]] = None
        if resume is not None and resume.cursor is not None:
            initial_paginator_state = {"cursor": resume.cursor}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only while a next page remains; the framework calls the hook AFTER a page is
            # yielded, so a crash re-yields the last batch (merge dedupes on primary key) rather
            # than skipping it.
            if state is not None and state.get("cursor") is not None:
                resumable_source_manager.save_state(CultureAmpResumeConfig(cursor=state["cursor"]))

        endpoint_config: Endpoint = {
            "path": config.path,
            "params": params,
            "data_selector": "data",
        }
        rest_config = {
            "client": _client_config(auth),
            "resources": [{"name": endpoint, "endpoint": endpoint_config}],
        }
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
        primary_keys=list(config.primary_keys) if config.primary_keys else None,
        partition_count=1,
        partition_size=1,
        # Result ordering within an after_date window is undocumented, so the pipeline defers
        # incremental watermark commits until a run completes.
        sort_mode="desc" if config.incremental_fields else "asc",
    )


def validate_credentials(client_id: str, client_secret: str, account_id: str) -> bool:
    """Confirm the credentials are valid by minting an employees-read token and probing /employees."""
    auth = _make_auth(client_id, client_secret, account_id, _VALIDATE_SCOPES)
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(client_secret,)),
        f"{CULTURE_AMP_BASE_URL}/employees",
        auth=auth,
        # 200 means the token minted and /employees is readable. 403 means the token minted (the
        # credentials are valid) but lacks the employees scope — accept at create time, matching
        # the old mint-only check; the sync-time non-retryable copy guides the permission fix.
        ok_statuses=(200, 403),
    )
    return ok
