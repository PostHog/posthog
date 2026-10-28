import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    make_parent_key_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.settings import PHYLLO_ENDPOINTS

# Credentials are environment-specific: a sandbox client ID/secret pair only authenticates against
# the sandbox host, so the environment select on the source form picks the base URL.
PHYLLO_BASE_URLS: dict[str, str] = {
    "production": "https://api.getphyllo.com",
    "sandbox": "https://api.sandbox.getphyllo.com",
}
# Documented maximum page size for Phyllo list endpoints.
PAGE_SIZE = 100
ACCOUNTS_PATH = "/v1/accounts"
# Phyllo documents no lower bound for a required date window, so a full refresh starts far enough
# back to cover the whole history of an account.
DATE_WINDOW_START = date(2000, 1, 1)
# Cheap list endpoint used to confirm a client ID/secret pair is genuine. Phyllo credentials are
# environment-wide, so one probe validates access to every endpoint.
DEFAULT_PROBE_PATH = "/v1/work-platforms"


@dataclasses.dataclass
class PhylloResumeConfig:
    # Legacy fields from the hand-rolled fan-out (a per-stream offset plus the account whose rows
    # were in flight). Kept (now with defaults) so state written by the previous implementation
    # still deserializes via `ResumableSourceManager._load_json`.
    offset: int = 0
    account_id: str | None = None
    # Framework paginator / fan-out resume snapshot for the current endpoint. When only the legacy
    # fields are present (old saved state) this is None and the sync restarts from the first page —
    # a re-fetch, which the merge dedupes on the primary key.
    paginator_state: Optional[dict[str, Any]] = None


def get_base_url(environment: str) -> str:
    return PHYLLO_BASE_URLS.get(environment, PHYLLO_BASE_URLS["production"])


def _base_headers() -> dict[str, str]:
    # Auth (Basic) is supplied via the framework config so the secret is redacted from raised
    # errors; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _date_window_params(endpoint: str, today: date) -> dict[str, str]:
    config = PHYLLO_ENDPOINTS[endpoint]
    if config.date_window_params is None:
        return {}

    from_param, to_param = config.date_window_params
    return {from_param: DATE_WINDOW_START.isoformat(), to_param: today.isoformat()}


def _child_endpoint(path: str, params: dict[str, Any], *, single_object: bool = False) -> Endpoint:
    if single_object:
        return {"path": path, "params": params, "data_selector": "$", "paginator": SinglePagePaginator()}
    return {
        "path": path,
        "params": params,
        "data_selector": "data",
        # Dependent resources can't classify a malformed 200 body as retryable, so fail loud
        # instead of silently syncing 0 rows if the response shape changes.
        "data_selector_required": True,
        "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
    }


def _build_resources(endpoint: str, extra_params: dict[str, str]) -> list[EndpointResource | str]:
    config = PHYLLO_ENDPOINTS[endpoint]

    if not config.fan_out_by_account:
        # A 200 body without `data` is an unexpected shape; treat it as transient and re-issue the
        # request (the old hand-rolled fetch raised a retryable error on the same condition).
        return [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "data_selector": "data",
                    "data_selector_malformed_retryable": True,
                    "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
                },
            }
        ]

    # Fan-out endpoints need an `account_id` query param, so enumerate connected accounts and pull
    # each account's rows in turn. The account id rides in a query param; embed the placeholder in
    # the path so the resolve binding lands in the query string (the resolve mechanism only
    # substitutes into the path). Child rows keep their own shape (no parent id injected).
    accounts_parent: EndpointResource = {
        "name": "accounts",
        "endpoint": {
            "path": ACCOUNTS_PATH,
            "data_selector": "data",
            "data_selector_malformed_retryable": True,
            "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
        },
    }
    account_id_param = {"type": "resolve", "resource": "accounts", "field": "id"}

    if config.fan_out_by_content:
        # The parent account id is carried onto each content row, so the comments request can bind
        # both ids from one parent row. The injected key is not in the comment rows.
        contents_parent: EndpointResource = {
            "name": "social_contents",
            "endpoint": _child_endpoint(
                f"{PHYLLO_ENDPOINTS['social_contents'].path}?account_id={{account_id}}",
                {"account_id": account_id_param},
            ),
            "include_from_parent": ["id"],
        }
        comments: EndpointResource = {
            "name": endpoint,
            "endpoint": _child_endpoint(
                f"{config.path}?account_id={{account_id}}&content_id={{content_id}}",
                {
                    "account_id": {
                        "type": "resolve",
                        "resource": "social_contents",
                        "field": make_parent_key_name("accounts", "id"),
                    },
                    "content_id": {"type": "resolve", "resource": "social_contents", "field": "id"},
                },
            ),
            "include_from_parent": [],
        }
        return [accounts_parent, contents_parent, comments]

    child: EndpointResource = {
        "name": endpoint,
        "endpoint": _child_endpoint(
            f"{config.path}?account_id={{account_id}}",
            {"account_id": account_id_param, **extra_params},
            single_object=config.single_object,
        ),
        "include_from_parent": [],
    }
    return [accounts_parent, child]


def endpoint_supports_resume(endpoint: str) -> bool:
    # The framework cannot checkpoint the two-level accounts -> contents -> comments fan-out, so a
    # retry of that table starts again from the first account.
    return not PHYLLO_ENDPOINTS[endpoint].fan_out_by_content


def phyllo_source(
    client_id: str,
    client_secret: str,
    environment: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PhylloResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PHYLLO_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": get_base_url(environment),
            "headers": _base_headers(),
            "auth": {"type": "http_basic", "username": client_id, "password": client_secret},
            # Phyllo has no top-level `total`; termination is a short/empty page (OffsetPaginator
            # default). Each resource gets a deep copy, so parent and child don't share state.
            "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
        },
        "resource_defaults": {},
        "resources": _build_resources(endpoint, _date_window_params(endpoint, datetime.now(UTC).date())),
    }

    supports_resume = endpoint_supports_resume(endpoint)
    initial_paginator_state: Optional[dict[str, Any]] = None
    if supports_resume and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.paginator_state is not None:
            initial_paginator_state = resume.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework saves AFTER a page is yielded so a crash re-yields the last page (merge
        # dedupes on the primary key) rather than skipping it.
        if state:
            resumable_source_manager.save_state(PhylloResumeConfig(paginator_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint if supports_resume else None,
        initial_paginator_state=initial_paginator_state,
    )
    target = next(resource for resource in resources if resource.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: target,
        primary_keys=config.primary_keys,
        # Phyllo doesn't guarantee ordering or a stable creation timestamp on every object, so we
        # don't partition.
        partition_count=1,
        partition_size=1,
        column_hints=target.column_hints,
        supports_resume=supports_resume,
    )


def validate_credentials(client_id: str, client_secret: str, environment: str) -> tuple[bool, str | None]:
    """Probe a single endpoint to validate the client ID/secret pair.

    Credentials are environment-wide, so one probe validates access to every schema.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(client_secret,)),
        f"{get_base_url(environment)}{DEFAULT_PROBE_PATH}?limit=1&offset=0",
        auth=HTTPBasicAuth(client_id, client_secret),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Phyllo client ID or secret for the selected environment"
    if status is None:
        return False, "Could not validate Phyllo credentials"
    return False, f"Phyllo returned HTTP {status}"
