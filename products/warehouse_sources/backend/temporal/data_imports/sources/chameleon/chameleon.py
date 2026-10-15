import itertools
from collections.abc import Callable, Iterator
from typing import Any, Optional

from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.settings import (
    CHAMELEON_ENDPOINTS,
    ChameleonEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    make_parent_key_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# Single base URL for every account — Chameleon has no per-account hostname.
CHAMELEON_BASE_URL = "https://api.chameleon.io/v3"
# The account-secret probe hits the root, which echoes back the account/user ids on success.
CHAMELEON_ROOT_URL = "https://api.chameleon.io"


@frozen
class ChameleonResumeConfig:
    # Cursor for the next page: the `cursor.before` id from the previous response. None starts at page one.
    before: str | None = None
    # Pre-framework fan-out bookmark (the Microsurvey being paged through). Kept with a default so
    # previously saved state still parses; no longer written — fan-out resume lives in fanout_state.
    survey_id: str | None = None
    # Framework fan-out resume state for a fan-out endpoint:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}.
    fanout_state: dict | None = None


class ChameleonBeforeCursorPaginator(JSONResponseCursorPaginator):
    """Chameleon returns records newest-first and paginates with a `cursor.before` id pointing at the
    oldest record on the page; the next page is fetched with `before=<that id>`. Pagination stops once
    a page is empty, the cursor is exhausted, or the cursor fails to advance (a defensive guard against
    an unexpected repeated cursor wedging the sync in an infinite loop).
    """

    def __init__(self) -> None:
        super().__init__(cursor_path="cursor.before", cursor_param="before")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        previous = self._cursor_value
        super().update_state(response, data)
        if not data or (self._cursor_value is not None and self._cursor_value == previous):
            self._has_next_page = False


def _client_config(account_secret: str) -> ClientConfig:
    # The account secret rides in a custom `X-Account-Secret` header the name-based scrubbers don't
    # recognise — framework api_key auth registers it for value-based redaction.
    return {
        "base_url": CHAMELEON_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": account_secret, "name": "X-Account-Secret", "location": "header"},
    }


def validate_credentials(account_secret: str) -> tuple[bool, str | None]:
    # The root probe echoes back the account/user ids on success (200). A bad or revoked secret is
    # rejected with 401/403 — those are the only conclusive "invalid" signals. Transport failures and
    # unexpected statuses (429, 5xx) are inconclusive: reporting them as an invalid secret would push
    # users to needlessly rotate a working credential, so they get a generic retry message instead.
    # `redact_values` masks the secret from any captured sample.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(account_secret,)),
        CHAMELEON_ROOT_URL,
        headers={"X-Account-Secret": account_secret, "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Chameleon account secret"
    if status is None:
        return False, "Could not reach Chameleon to validate the account secret. Please try again."
    return (
        False,
        f"Chameleon could not validate the account secret right now (status {status}). Please try again.",
    )


def _page_params(config: ChameleonEndpointConfig) -> dict[str, Any]:
    return {"limit": config.page_size} if config.page_size is not None else {}


def _standard_resource(
    account_secret: str,
    config: ChameleonEndpointConfig,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[ChameleonResumeConfig],
) -> Resource:
    # A body without the data key yields a zero-row page and pagination stops — the same tolerant
    # behavior Chameleon's empty envelopes get.
    rest_config: RESTAPIConfig = {
        "client": _client_config(account_secret),
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": _page_params(config),
                    "paginator": ChameleonBeforeCursorPaginator(),
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        if resume is not None and resume.before:
            initial_paginator_state = {"cursor": resume.before}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the checkpoint is saved AFTER a page is yielded so a
        # crash re-fetches the in-flight page (the merge dedupes re-pulled rows) rather than skipping it.
        if state and state.get("cursor"):
            manager.save_state(ChameleonResumeConfig(before=state["cursor"]))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _stamp_parent_id(parent_name: str, column: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Rename the parent id `include_from_parent` injects to the plain join column child rows carry.

    Where the API already returns that column (interactions' `tour_id`) the value is the same one —
    every row came back from a request filtered to that parent.
    """
    injected_key = make_parent_key_name(parent_name, "id")

    def stamp(row: dict[str, Any]) -> dict[str, Any]:
        value = row.pop(injected_key, None)
        if value is not None:
            row[column] = value
        return row

    return stamp


def _fan_out_resource(
    account_secret: str,
    config: ChameleonEndpointConfig,
    parent_name: str,
    parent_key_column: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[ChameleonResumeConfig],
) -> Resource:
    """Fan out over every parent record, listing this endpoint per parent and stamping the parent id.

    /analyze/responses and /analyze/interactions both require an `id` (the Microsurvey and the Tour
    respectively), so their rows can only be pulled one parent at a time. Full refresh — re-pulled
    rows on resume are deduped by the `id` primary key on merge.
    """
    parent_config = CHAMELEON_ENDPOINTS[parent_name]

    rest_config: RESTAPIConfig = {
        "client": _client_config(account_secret),
        "resources": [
            {
                "name": parent_name,
                "endpoint": {
                    "path": parent_config.path,
                    "params": _page_params(parent_config),
                    "paginator": ChameleonBeforeCursorPaginator(),
                    "data_selector": parent_config.data_key,
                },
            },
            {
                "name": config.name,
                "endpoint": {
                    # The parent id is a required QUERY param; the framework binds resolve params via
                    # path templating, so the query string rides in the path (requests merges the
                    # remaining params into it).
                    "path": f"{config.path}?id={{id}}",
                    "params": {
                        "id": {"type": "resolve", "resource": parent_name, "field": "id"},
                        **_page_params(config),
                    },
                    "paginator": ChameleonBeforeCursorPaginator(),
                    "data_selector": config.data_key,
                    # A parent deleted between enumeration and this fetch 404s. Skip it rather than
                    # failing the whole sync — its child records are genuinely gone.
                    "response_actions": [{"status_code": 404, "action": "ignore"}],
                },
                "include_from_parent": ["id"],
                "data_map": _stamp_parent_id(parent_name, parent_key_column),
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        # Only framework-shaped fan-out state is resumable. A pre-migration bookmark (survey_id +
        # before) can't be translated into the completed/current path map, so such a sync restarts
        # fresh — safe, because the merge dedupes re-pulled rows on the primary key.
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            manager.save_state(ChameleonResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(r for r in resources if r.name == config.name)


def _stamp_kind(kind: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    # The documented list payload does not echo `kind` back, and profile and company property
    # definitions share one table, so stamp the kind each request filtered on.
    def stamp(row: dict[str, Any]) -> dict[str, Any]:
        row["kind"] = kind
        return row

    return stamp


def _kind_resources(
    account_secret: str,
    config: ChameleonEndpointConfig,
    team_id: int,
    job_id: str,
) -> list[Resource]:
    """One resource per required `kind` value, read back to back into a single table.

    /edit/properties returns the whole matching set in one response, so each kind is a single page.
    """
    resources: list[Resource] = []
    for kind in config.kinds:
        rest_config: RESTAPIConfig = {
            "client": _client_config(account_secret),
            "resources": [
                {
                    "name": f"{config.name}_{kind}",
                    "endpoint": {
                        "path": f"{config.path}?kind={kind}",
                        "paginator": SinglePagePaginator(),
                        "data_selector": config.data_key,
                    },
                    "data_map": _stamp_kind(kind),
                }
            ],
        }
        resources.append(rest_api_resource(rest_config, team_id, job_id, None))
    return resources


def chameleon_source(
    account_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ChameleonResumeConfig],
) -> SourceResponse:
    endpoint_config: ChameleonEndpointConfig = CHAMELEON_ENDPOINTS[endpoint]

    resources: list[Resource]
    if endpoint_config.fan_out_parent is not None and endpoint_config.fan_out_parent_key is not None:
        resources = [
            _fan_out_resource(
                account_secret,
                endpoint_config,
                endpoint_config.fan_out_parent,
                endpoint_config.fan_out_parent_key,
                team_id,
                job_id,
                resumable_source_manager,
            )
        ]
    elif endpoint_config.kinds:
        resources = _kind_resources(account_secret, endpoint_config, team_id, job_id)
    else:
        resources = [_standard_resource(account_secret, endpoint_config, team_id, job_id, resumable_source_manager)]

    def items() -> Iterator[Any]:
        return itertools.chain.from_iterable(resources)

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        # Chameleon returns records most-recently-created first.
        sort_mode="desc",
        column_hints=resources[0].column_hints,
    )
