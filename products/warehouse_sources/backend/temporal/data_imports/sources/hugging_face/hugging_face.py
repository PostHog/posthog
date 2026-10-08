import dataclasses
from collections.abc import Callable, Iterator
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.settings import (
    HUGGING_FACE_ENDPOINTS,
    REPO_KINDS,
    HuggingFaceEndpointConfig,
)

HUGGING_FACE_BASE_URL = "https://huggingface.co"

# The Hub answers 403 with this body for a repo whose owner turned discussions off.
DISCUSSIONS_DISABLED_ERROR = "Discussions are disabled for this repo"


@dataclasses.dataclass(frozen=True)
class HuggingFaceResumeConfig:
    # URL of the page to resume from. We checkpoint the *next* page's self-contained Link-header URL
    # after a page is yielded, so a resumed run continues from where it left off (already-yielded
    # pages are persisted before the checkpoint; the delta merge dedupes on the primary key).
    resume_url: Optional[str] = None
    # The rest_source fan-out state for discussions: child paths already synced plus the one in progress.
    fanout_state: Optional[dict[str, Any]] = None


class HuggingFaceLinkPaginator(HeaderLinkPaginator):
    """Follows the Hub's ``Link: <…>; rel="next"`` cursor, but also stops on an empty page.

    The Hub omits the next link once it runs out of rows, but we terminate on an empty page even if a
    stray next link is present — matching the original source's "empty page ends the stream" guard and
    avoiding an unbounded loop.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)


class HuggingFaceDiscussionsPaginator(PageNumberPaginator):
    """Pages a repo's discussions with ``?p=``, stopping once ``start + len(page)`` reaches ``count``.

    Stopping on the reported total saves the trailing empty-page request, which the fan-out would
    otherwise pay once per repo.
    """

    def __init__(self) -> None:
        super().__init__(base_page=0, page_param="p")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page or not data:
            return
        try:
            body = response.json()
        except ValueError:
            return
        start, count = body.get("start"), body.get("count")
        if isinstance(start, int) and isinstance(count, int) and start + len(data) >= count:
            self._has_next_page = False


def hugging_face_source(
    api_token: str,
    endpoint: str,
    author: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HuggingFaceResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HUGGING_FACE_ENDPOINTS[endpoint]
    client: ClientConfig = {
        "base_url": HUGGING_FACE_BASE_URL,
        # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
        # logs and raised errors; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_token},
        "paginator": HuggingFaceLinkPaginator(),
    }

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.kind == "tags":
        resource = _tags_resource(client, config, team_id, job_id)
    elif config.kind == "discussions":

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(HuggingFaceResumeConfig(fanout_state=state))

        resource = _discussions_resource(
            client,
            config,
            author,
            team_id,
            job_id,
            resume_hook=save_fanout_checkpoint,
            initial_state=resume.fanout_state if resume else None,
        )
    else:

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; save AFTER a page is yielded so a resumed run picks
            # up at the next self-contained Link-header URL.
            if state and state.get("next_url"):
                resumable_source_manager.save_state(HuggingFaceResumeConfig(resume_url=state["next_url"]))

        resource = _list_resource(
            client,
            config,
            author,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_state={"next_url": resume.resume_url} if resume and resume.resume_url else None,
        )

    partitioning: dict[str, Any] = {}
    if config.partition_key:
        partitioning = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [config.partition_key],
        }

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        column_hints=resource.column_hints,
        # The tag lookups are one request with no cursor to checkpoint.
        supports_resume=config.kind != "tags",
        **partitioning,
    )


def _list_resource(
    client: ClientConfig,
    config: HuggingFaceEndpointConfig,
    author: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    resume_hook: Callable[[Optional[dict[str, Any]]], None],
    initial_state: Optional[dict[str, Any]],
) -> Resource:
    endpoint: Endpoint = {
        "path": config.path.replace("{author}", author),
        "params": _build_initial_params(config, author),
    }
    if not config.stop_on_empty_page:
        endpoint["paginator"] = HeaderLinkPaginator()
    if config.ignore_not_found:
        endpoint["response_actions"] = [{"status_code": 404, "action": "ignore"}]

    resource = rest_api_resource(
        {"client": client, "resources": [{"name": config.name, "endpoint": endpoint}]},
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=resume_hook,
        initial_paginator_state=initial_state,
    )
    if config.flatten_repo:
        resource.add_map(_flatten_repo)
    return resource


def _tags_resource(client: ClientConfig, config: HuggingFaceEndpointConfig, team_id: int, job_id: str) -> Resource:
    resource = rest_api_resource(
        {
            "client": client,
            "resources": [{"name": config.name, "endpoint": {"path": config.path, "paginator": "single_page"}}],
        },
        team_id,
        job_id,
        None,
    )
    return resource.add_map(_tag_rows)


def _discussions_resource(
    client: ClientConfig,
    config: HuggingFaceEndpointConfig,
    author: str,
    team_id: int,
    job_id: str,
    resume_hook: Callable[[Optional[dict[str, Any]]], None],
    initial_state: Optional[dict[str, Any]],
) -> Resource:
    # One parent stream over every repo kind keeps the fan-out a single dependent resource, so the
    # framework's per-parent resume covers models, datasets and Spaces together.
    parent: EndpointResource = {
        "name": "repos",
        "endpoint": {"path": "/api/models"},
        "data_iterator": lambda: _repo_pages(client, author, team_id, job_id),
    }
    child: EndpointResource = {
        "name": config.name,
        "endpoint": {
            "path": config.path,
            "params": {
                "repo_kind": {"type": "resolve", "resource": "repos", "field": "repo_kind"},
                "repo_id": {"type": "resolve", "resource": "repos", "field": "id"},
            },
            "paginator": HuggingFaceDiscussionsPaginator(),
            "data_selector": "discussions",
            "response_actions": [
                {
                    "status_code": 403,
                    "json_field": "error",
                    "json_values": [DISCUSSIONS_DISABLED_ERROR],
                    "action": "ignore",
                },
                # A repo deleted between the listing and its discussions fetch.
                {"status_code": 404, "action": "ignore"},
            ],
        },
    }
    resources = rest_api_resources(
        {"client": client, "resources": [parent, child]},
        team_id,
        job_id,
        None,
        resume_hook=resume_hook,
        initial_paginator_state=initial_state,
    )
    resource = next(r for r in resources if r.name == config.name)
    return resource.add_map(_flatten_repo)


def _repo_pages(client: ClientConfig, author: str, team_id: int, job_id: str) -> Iterator[list[dict[str, Any]]]:
    for kind in REPO_KINDS:
        repo_config = HUGGING_FACE_ENDPOINTS[kind]
        # The fan-out only needs repo ids, so skip the heavier `full` payload.
        params = {key: value for key, value in _build_initial_params(repo_config, author).items() if key != "full"}
        resource = rest_api_resource(
            {"client": client, "resources": [{"name": kind, "endpoint": {"path": repo_config.path, "params": params}}]},
            team_id,
            job_id,
            None,
        )
        for page in resource:
            yield [{"repo_kind": kind, "id": row["id"]} for row in page]


def _flatten_repo(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "repo_type": row["repo"]["type"], "repo_name": row["repo"]["name"]}


def _tag_rows(tags_by_type: dict[str, Any]) -> list[dict[str, Any]]:
    # Each tag already carries its `type`, so flattening the per-type groups loses nothing.
    return [tag for tags in tags_by_type.values() for tag in tags]


def validate_credentials(api_token: str) -> bool:
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{HUGGING_FACE_BASE_URL}/api/whoami-v2",
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
    )
    return ok


def _build_initial_params(config: HuggingFaceEndpointConfig, author: str) -> dict[str, Any]:
    # The Hub has no server-side timestamp range filter, so these endpoints are full refresh only.
    params: dict[str, Any] = dict(config.params)
    if config.author_param:
        params[config.author_param] = author
    return params
