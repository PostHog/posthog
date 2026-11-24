from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import structlog
from jsonpath_ng import DatumInContext, JSONPath
from requests import HTTPError, RequestException

from products.warehouse_sources.sources.sdk import (
    APIKeyAuth,
    ClientConfig,
    Endpoint,
    OffsetPaginator,
    Resource,
    RESTAPIConfig,
    RESTClient,
    RESTClientRetryableError,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    create_response_hooks,
    frozen,
    rest_api_resource,
    schema_for_resource,
)
from products.warehouse_sources.sources.vwo.settings import (
    API_ORIGIN,
    ENDPOINTS,
    FEATURE_FLAG_RULES_CHILD_ACTIONS,
    VWOEndpoint,
)

logger = structlog.get_logger(__name__)


@frozen
class VWOResumeConfig:
    paginator_state: dict[str, Any]


def vwo_error_detail(body: Any) -> str:
    # VWO can report a failure as a 200 with an `_errors` list, so its message must reach the error classifier.
    errors = body.get("_errors") if isinstance(body, dict) else None
    if not isinstance(errors, list):
        return ""
    messages = [
        f"{error['code']}: {error['message']}" if error.get("code") is not None else str(error["message"])
        for error in errors
        if isinstance(error, dict) and error.get("message")
    ]
    return f" ({'; '.join(messages)[:200]})" if messages else ""


class VWOCollectionSelector(JSONPath):
    # The campaign example is malformed. Accept flat and partialCollection envelopes without selecting nested goals.
    def __init__(self, skip_missing_envelope: bool = False) -> None:
        # Per-campaign child responses can come back with neither `_data` nor `_errors`. One such campaign
        # must not fail the whole fan-out, so it reads as an empty page. Responses with `_errors` still fail.
        self.skip_missing_envelope = skip_missing_envelope

    def find(self, data: Any) -> list[DatumInContext]:
        if not isinstance(data, dict) or "_data" not in data:
            if self.skip_missing_envelope and not (isinstance(data, dict) and "_errors" in data):
                logger.warning(
                    "vwo_child_response_without_data_envelope",
                    body_type=type(data).__name__,
                    keys=sorted(data)[:10] if isinstance(data, dict) else None,
                )
                return [DatumInContext([])]
            raise ValueError(
                f"VWO returned no data envelope{vwo_error_detail(data)}. Check the token permissions and API response."
            )
        rows = data["_data"]
        if isinstance(rows, dict) and "partialCollection" in rows:
            rows = rows["partialCollection"]
        if rows is None or rows == {}:
            rows = []
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("VWO returned an unsupported collection. Check the API response.")
        return [DatumInContext(rows)]


def client_config(api_token: str, api_version: str) -> ClientConfig:
    return {
        "base_url": f"{API_ORIGIN}/{api_version}/",
        "auth": {"type": "api_key", "api_key": api_token, "name": "token", "location": "header"},
        "headers": {"Accept": "application/json"},
        "request_timeout": (10, 30),
        "retry_budget_seconds": 180,
        "retry_after_max_seconds": 60,
        "allow_redirects": False,
        "allowed_hosts": [],
    }


def endpoint_config(endpoint: VWOEndpoint) -> Endpoint:
    return {
        "data_selector": "_data"
        if endpoint.singleton
        else VWOCollectionSelector(skip_missing_envelope=endpoint.fanout is not None),
        "data_selector_required": True,
        "paginator": {"type": "offset", "limit": endpoint.page_size, "total_path": "_data.totalCount"}
        if endpoint.paginated
        else "single_page",
    }


def normalize_row(endpoint: VWOEndpoint, row: dict[str, Any]) -> dict[str, Any]:
    if endpoint.name == "projects" and isinstance(row.get("environments"), list):
        # `token` is the SDK key of the environment, a credential that does not belong in the warehouse.
        row["environments"] = [
            {key: value for key, value in environment.items() if key != "token"}
            if isinstance(environment, dict)
            else environment
            for environment in row["environments"]
        ]
    if endpoint.partition_field:
        value = row.get(endpoint.partition_field)
        row["created_at"] = datetime.fromtimestamp(float(value), tz=UTC) if value is not None else None
    if endpoint.name == "variations":
        # Some variation responses omit sectionId. Zero keeps the composite key non-null.
        row["sectionId"] = row.get("sectionId") or 0
    return row


def rest_client(api_token: str, api_version: str) -> RESTClient:
    config = client_config(api_token, api_version)
    return RESTClient(
        base_url=config["base_url"],
        headers=config["headers"],
        auth=APIKeyAuth(api_key=api_token, name="token", location="header"),
        request_timeout=config["request_timeout"],
        retry_budget_seconds=config["retry_budget_seconds"],
        retry_after_max_seconds=config["retry_after_max_seconds"],
        allow_redirects=False,
        allowed_hosts=[],
    )


def _pages(
    client: RESTClient, endpoint: VWOEndpoint, path: str, hooks: dict[str, Any] | None = None
) -> Iterator[list[dict[str, Any]]]:
    paginator = (
        OffsetPaginator(limit=endpoint.page_size, total_path="_data.totalCount")
        if endpoint.paginated
        else SinglePagePaginator()
    )
    yield from client.paginate(
        path=path,
        paginator=paginator,
        data_selector=VWOCollectionSelector(skip_missing_envelope=hooks is not None),
        data_selector_required=True,
        hooks=hooks,
    )


def feature_flag_rule_rows(
    client: RESTClient,
    account_id: str,
    resumable_source_manager: ResumableSourceManager[VWOResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Read the rules of every feature flag in every FE environment.

    VWO lists rules per environment and flag only, so this pairs each environment of each project
    with each flag of the workspace. Pairs are read in id order, and the resume state is the last
    pair read.
    """
    endpoint = ENDPOINTS["feature_flag_rules"]
    environments: dict[int, Any] = {}
    for page in _pages(client, ENDPOINTS["projects"], ENDPOINTS["projects"].path.format(account_id=account_id)):
        for project in page:
            for environment in project.get("environments") or []:
                if isinstance(environment, dict) and environment.get("id") is not None:
                    environments.setdefault(int(environment["id"]), project.get("id"))
        resumable_source_manager.safe_point()
    feature_ids: set[int] = set()
    flags = ENDPOINTS["feature_flags"]
    for page in _pages(client, flags, flags.path.format(account_id=account_id)):
        feature_ids.update(int(feature["id"]) for feature in page if feature.get("id") is not None)
        resumable_source_manager.safe_point()

    done: tuple[int, int] | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and "environment_id" in resume.paginator_state:
            done = (int(resume.paginator_state["environment_id"]), int(resume.paginator_state["feature_id"]))

    hooks = create_response_hooks(FEATURE_FLAG_RULES_CHILD_ACTIONS)
    for environment_id in sorted(environments):
        for feature_id in sorted(feature_ids):
            if done is not None and (environment_id, feature_id) <= done:
                continue
            path = endpoint.path.format(account_id=account_id, environment_id=environment_id, feature_id=feature_id)
            rows = [
                {
                    **rule,
                    "project_id": environments[environment_id],
                    "environment_id": environment_id,
                    "feature_id": feature_id,
                }
                for page in _pages(client, endpoint, path, hooks)
                for rule in page
            ]
            resumable_source_manager.save_state(
                VWOResumeConfig(paginator_state={"environment_id": environment_id, "feature_id": feature_id})
            )
            if rows:
                yield rows
            else:
                resumable_source_manager.safe_point()


def validate_credentials(api_token: str, account_id: str, api_version: str) -> tuple[bool, str | None]:
    client = rest_client(api_token, api_version)
    try:
        page = next(
            client.paginate(path=f"accounts/{account_id}", data_selector="_data", paginator=SinglePagePaginator())
        )
        if not page or not isinstance(page[0], dict) or "id" not in page[0]:
            return False, "VWO returned no workspace. Check the workspace ID and token permissions."
        return True, None
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, "VWO rejected the API token. Generate a new token and reconnect."
        if status == 403:
            return False, "The VWO token cannot read this workspace. Check the token permissions and workspace ID."
        if status == 404:
            return False, "VWO could not find this workspace. Check the workspace ID."
        return False, "VWO rejected the connection request. Check the workspace ID and token permissions."
    except (RequestException, RESTClientRetryableError, ValueError):
        return False, "Could not connect to VWO. Try again."


def vwo_source(
    api_token: str,
    account_id: str,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[VWOResumeConfig],
) -> SourceResponse:
    metadata = schema_for_resource(ENDPOINTS, endpoint)
    client = client_config(api_token, api_version)
    initial_state: dict[str, Any] | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_state = resume.paginator_state

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(VWOResumeConfig(paginator_state=state))

    if endpoint == "feature_flag_rules":
        return SourceResponse(
            name=endpoint,
            items=lambda: feature_flag_rule_rows(
                rest_client(api_token, api_version), account_id, resumable_source_manager
            ),
            primary_keys=list(metadata.primary_keys),
            sort_mode=None,
        )

    if metadata.fanout:
        resource = build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=endpoint,
            fanout=metadata.fanout,
            client_config=client,
            path_format_values={"account_id": account_id},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=endpoint_config(ENDPOINTS[metadata.fanout.parent_name]),
            child_endpoint_extra=endpoint_config(metadata),
            page_size_param=None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        )
        assert isinstance(resource, Resource)
    else:
        config: RESTAPIConfig = {
            "client": client,
            "resources": [
                {
                    "name": endpoint,
                    "table_name": endpoint,
                    "write_disposition": "replace",
                    "table_format": "delta",
                    "endpoint": {**endpoint_config(metadata), "path": metadata.path.format(account_id=account_id)},
                }
            ],
        }
        resource = rest_api_resource(
            config, team_id, job_id, None, resume_hook=save_checkpoint, initial_paginator_state=initial_state
        )
    resource.add_map(lambda row: normalize_row(metadata, row))
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(metadata.primary_keys),
        partition_mode="datetime" if metadata.partition_field else None,
        partition_keys=["created_at"] if metadata.partition_field else None,
        partition_format="month" if metadata.partition_field else None,
        sort_mode=None,
    )
