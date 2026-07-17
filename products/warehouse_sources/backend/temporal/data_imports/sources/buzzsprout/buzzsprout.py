import re

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.settings import (
    BUZZSPROUT_ENDPOINTS,
    BuzzsproutEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

BUZZSPROUT_BASE_URL = "https://www.buzzsprout.com/api"

# Buzzsprout blocks requests sent with a default/bot User-Agent, so we identify ourselves explicitly.
USER_AGENT = "PostHog Data Warehouse (https://posthog.com)"


def _auth_header_value(api_token: str) -> str:
    # Buzzsprout's documented auth scheme is a static account token in the Authorization header,
    # using a custom `Token token=` prefix rather than standard Bearer.
    return f"Token token={api_token}"


# A Buzzsprout podcast ID is a bare identifier (numeric in practice). `podcast_id` is a non-secret,
# editable field that ends up as a REST path segment, so anything that could make that path resolve
# to a different origin — a URL scheme, path separators, a query/fragment marker, whitespace, or a
# `..` traversal — is rejected. Otherwise a value like `https://attacker.example/../<id>` would be
# treated as an absolute URL by the request layer and the stored token sent to the attacker's host.
_INVALID_PODCAST_ID = re.compile(r"[\s/\\?#:]|\.\.")


def _clean_podcast_id(podcast_id: str) -> str:
    cleaned = podcast_id.strip()
    if not cleaned:
        raise ValueError("A Buzzsprout podcast ID is required.")
    if _INVALID_PODCAST_ID.search(cleaned):
        raise ValueError("Invalid Buzzsprout podcast ID. Enter the numeric ID from your Buzzsprout API settings.")
    return cleaned


def _build_path(podcast_id: str, config: BuzzsproutEndpointConfig) -> str:
    if config.account_scoped:
        return config.path
    return f"{podcast_id}/{config.path}"


def validate_credentials(api_token: str, podcast_id: str) -> tuple[bool, str | None]:
    try:
        podcast_id = _clean_podcast_id(podcast_id)
    except ValueError as e:
        return False, str(e)

    # The episodes endpoint is scoped to the podcast_id, so a 200 confirms both the token and the ID
    # in a single cheap probe.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{BUZZSPROUT_BASE_URL}/{podcast_id}/episodes.json",
        headers={
            "Authorization": _auth_header_value(api_token),
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    if ok:
        return True, None
    if status is None:
        return False, "Could not reach the Buzzsprout API. Please try again."
    if status in (401, 403):
        return False, "Invalid Buzzsprout API token. Create a new token in your Buzzsprout account settings."
    if status == 404:
        return False, "Buzzsprout podcast not found. Check the podcast ID."
    # A transient 429/5xx (after the session's own retries are exhausted) is not a credential problem,
    # so surface it as a retryable condition rather than rejecting otherwise-valid credentials.
    if status == 429 or status >= 500:
        return False, "Buzzsprout API is temporarily unavailable. Please try again in a moment."

    return False, f"Buzzsprout API returned an unexpected status code: {status}"


def buzzsprout_source(api_token: str, podcast_id: str, endpoint: str, team_id: int, job_id: str) -> SourceResponse:
    config = BUZZSPROUT_ENDPOINTS[endpoint]
    # Guard the sync path with the same check as validation so an edited-in absolute/traversal
    # podcast_id can never retarget the authenticated request off the Buzzsprout host.
    podcast_id = _clean_podcast_id(podcast_id)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BUZZSPROUT_BASE_URL,
            # The token rides in the framework auth config so its value is redacted from logs;
            # only the non-secret headers are set here.
            "headers": {"User-Agent": USER_AGENT, "Accept": "application/json"},
            "auth": {
                "type": "api_key",
                "name": "Authorization",
                "api_key": _auth_header_value(api_token),
                "location": "header",
            },
            # Buzzsprout has no pagination: each endpoint returns its full array in one response,
            # so a single fetch is the whole table.
            "paginator": SinglePagePaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": _build_path(podcast_id, config),
                    # Every documented endpoint returns a bare JSON array; require a list so an
                    # unexpected object body fails loud instead of syncing it as a row.
                    "data_selector_required": True,
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
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
        column_hints=resource.column_hints,
    )
