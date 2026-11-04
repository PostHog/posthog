from collections.abc import Iterable
from typing import Any

from products.warehouse_sources.sources.groq.settings import GROQ_ENDPOINTS, GroqEndpointConfig
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    JSONResponseCursorPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    frozen,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


@frozen
class GroqResumeConfig:
    # The `paging.next_cursor` of the last page handed on. Only `batches` paginates.
    cursor: str | None = None
    # The last page is handed on, so a resume reads nothing again.
    completed: bool = False


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _paginator_for(config: GroqEndpointConfig) -> BasePaginator:
    # Only `batches` paginates, via a body cursor in `paging.next_cursor` echoed back as the `cursor`
    # query param. An empty/absent cursor (or a non-dict `paging`) ends pagination. files and models
    # are single flat `data` arrays with no documented pagination.
    if config.paginated:
        return JSONResponseCursorPaginator(cursor_path="paging.next_cursor", cursor_param="cursor")
    return SinglePagePaginator()


def groq_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GroqResumeConfig],
) -> SourceResponse:
    config: GroqEndpointConfig = GROQ_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": GROQ_BASE_URL,
            # Auth (Bearer) is supplied via the framework auth config so the token is redacted from
            # logs and raised error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": _paginator_for(config),
            # Redirects disabled so the bearer token is never replayed to another host.
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # All three list endpoints wrap results as {"object": "list", "data": [...]}.
                    "data_selector": "data",
                    # A 200 whose body isn't the expected shape (non-object, or `data` not a list) is
                    # treated as a transient malformation and retried, not ingested as a stray row.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(GroqResumeConfig(cursor=str(state["cursor"])))
        elif state is None:
            resumable_source_manager.save_state(GroqResumeConfig(completed=True))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"cursor": resume.cursor} if resume is not None and resume.cursor else None,
    )
    completed = resume is not None and resume.completed

    def items() -> Iterable[Any]:
        return [] if completed else resource

    return SourceResponse(
        name=endpoint,
        on_complete=resumable_source_manager.clear_state,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Confirm the API key is usable by listing models (cheap, always available with a valid key).

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` when the request never completed.
    """
    if not api_key.strip():
        return False, None

    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        f"{GROQ_BASE_URL}/models",
        headers=_get_headers(api_key),
    )
