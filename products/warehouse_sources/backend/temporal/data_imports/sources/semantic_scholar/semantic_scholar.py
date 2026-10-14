from typing import Any

from requests import Response
from requests.exceptions import HTTPError, RequestException
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTClient,
    RESTClientRetryableError,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.semanticscholar import (
    SemanticScholarSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.settings import (
    API_ROOT,
    AUTH_ERROR,
    EDGE_FIELDS,
    ENDPOINTS,
    LIMIT_ERROR,
    MAX_PAPERS,
    PAPER_FIELDS,
    PRIMARY_KEYS,
    QUERY_ERROR,
    RELATED_PAPER_FIELDS,
)


@frozen
class SemanticScholarResumeConfig:
    paginator_state: dict[str, Any]


def check_bulk_limit(response: Response, *args: object, **kwargs: object) -> None:
    if response.status_code == 200 and response.url and "/paper/search/bulk" in response.url:
        if int(response.json().get("total", 0)) > MAX_PAPERS:
            raise ValueError(LIMIT_ERROR)


def validate_credentials(config: SemanticScholarSourceConfig, api_version: str) -> tuple[bool, str | None]:
    if not config.api_key.strip() or not config.api_key.isascii() or any(c.isspace() for c in config.api_key):
        return False, "Enter an API key without spaces or unsupported characters."
    if not config.query.strip():
        return False, "Enter a search query for the papers you want to sync."
    try:
        client = RESTClient(
            base_url=f"{API_ROOT}/{api_version}",
            auth=APIKeyAuth(api_key=config.api_key, name="x-api-key"),
            session=make_tracked_session(retry=Retry(total=0), redact_values=(config.api_key,)),
            max_retry_attempts=1,
            request_timeout=30,
            allow_redirects=False,
            allowed_hosts=[],
        )
        try:
            next(
                client.paginate(
                    path="paper/search/bulk",
                    params={"query": config.query, "fields": "paperId"},
                    paginator=SinglePagePaginator(),
                    data_selector="data",
                    data_selector_required=True,
                )
            )
        finally:
            client.session.close()
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status in (401, 403):
            return False, AUTH_ERROR
        if status == 400:
            return False, QUERY_ERROR
        return False, "Semantic Scholar could not validate the connection. Try again later."
    except (RequestException, RESTClientRetryableError):
        return False, "Semantic Scholar is unavailable or has limited requests. Try again later."
    return True, None


def semantic_scholar_source(
    config: SemanticScholarSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SemanticScholarResumeConfig],
    api_version: str,
) -> SourceResponse:
    if inputs.schema_name not in ENDPOINTS:
        raise ValueError(f"Unknown Semantic Scholar table: {inputs.schema_name}")
    session = make_tracked_session(retry=Retry(total=0), redact_values=(config.api_key,))
    session.hooks["response"].append(check_bulk_limit)
    client: ClientConfig = {
        "base_url": f"{API_ROOT}/{api_version}",
        "auth": {"type": "api_key", "name": "x-api-key", "api_key": config.api_key, "location": "header"},
        "session": session,
        "request_timeout": 60,
        "allowed_hosts": [],
        "allow_redirects": False,
    }
    papers: EndpointResource = {
        "name": "papers",
        "endpoint": {
            "path": "paper/search/bulk",
            "params": {
                "query": config.query,
                "fields": PAPER_FIELDS if inputs.schema_name == "papers" else "paperId",
                "sort": "paperId:asc",
            },
            "data_selector": "data",
            "data_selector_required": True,
            "paginator": {
                "type": "cursor",
                "cursor_path": "token",
                "cursor_param": "token",
                "raise_on_repeated_cursor": True,
            },
        },
    }
    resources: list[str | EndpointResource] = [papers]
    if inputs.schema_name != "papers":
        resources.append(
            {
                "name": inputs.schema_name,
                "include_from_parent": ["paperId"],
                "endpoint": {
                    "path": f"paper/{{paper_id}}/{inputs.schema_name}",
                    "params": {
                        "paper_id": {"type": "resolve", "resource": "papers", "field": "paperId"},
                        "limit": 1000,
                        "fields": EDGE_FIELDS,
                    },
                    "data_selector": "data",
                    "data_selector_required": True,
                    "paginator": {
                        "type": "cursor",
                        "cursor_path": "next",
                        "cursor_param": "offset",
                        "raise_on_repeated_cursor": True,
                    },
                },
            }
        )
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(SemanticScholarResumeConfig(paginator_state=state))

    built = rest_api_resources(
        {"client": client, "resource_defaults": {"write_disposition": "replace"}, "resources": resources},
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=resume.paginator_state if resume else None,
    )
    resource = next(resource for resource in built if resource.name == inputs.schema_name)
    if inputs.schema_name != "papers":
        related_field = RELATED_PAPER_FIELDS[inputs.schema_name]

        def normalize_edge(row: dict[str, Any]) -> dict[str, Any]:
            row["paper_id"] = row.pop("_papers_paperId")
            row["related_paper_id"] = row[related_field]["paperId"]
            return row

        resource.add_filter(lambda row: bool((row.get(related_field) or {}).get("paperId")))
        resource.add_map(normalize_edge)
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[inputs.schema_name],
        sort_mode=None,
        on_complete=session.close,
    )
