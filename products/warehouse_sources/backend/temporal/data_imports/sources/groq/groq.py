from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.groq.settings import (
    GROQ_ENDPOINTS,
    GroqEndpointConfig,
)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


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

    resource = rest_api_resource(rest_config, team_id, job_id, None)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
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
