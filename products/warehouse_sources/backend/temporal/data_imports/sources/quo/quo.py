from collections.abc import Callable, Iterable, Iterator
from typing import Any, Optional

from requests import Session

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.quo.settings import (
    QUO_BASE_URL,
    QUO_ENDPOINTS,
    QuoEndpointConfig,
)


@frozen
class QuoResumeConfig:
    page_token: str


def _to_iso(value: Any) -> Optional[str]:
    """Coerce an incremental watermark to the ISO 8601 string Quo's `createdAfter`-style filters take."""
    parsed = parse_datetime_value(value)
    return parsed.isoformat() if parsed is not None else None


def _auth_headers(api_key: str) -> dict[str, str]:
    # Quo takes the raw API key in the Authorization header, with no Bearer prefix.
    return {"Accept": "application/json", "Authorization": api_key}


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is valid. /v1/phone-numbers is a cheap authenticated probe with no required params."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{QUO_BASE_URL}/v1/phone-numbers",
        headers=_auth_headers(api_key),
    )
    return ok


def _build_params(
    config: QuoEndpointConfig, cursor_field: Optional[str], watermark_iso: Optional[str]
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.page_size is not None:
        params["maxResults"] = config.page_size
    if watermark_iso is not None and cursor_field is not None:
        server_filter = config.incremental_params.get(cursor_field)
        if server_filter is not None:
            params[server_filter] = watermark_iso
    return params


def _paginate(session: Session, path: str, params: dict[str, Any]) -> Iterator[list[dict[str, Any]]]:
    """Yield pages of `data` rows, following the `nextPageToken` cursor until it runs out."""
    page_token: Optional[str] = None
    while True:
        page_params = dict(params)
        if page_token is not None:
            page_params["pageToken"] = page_token
        response = session.get(f"{QUO_BASE_URL}{path}", params=page_params)
        response.raise_for_status()
        body = response.json()
        rows = body.get("data") or []
        if rows:
            yield rows
        page_token = body.get("nextPageToken")
        if not page_token:
            return


def _fan_out_rows(api_key: str, config: QuoEndpointConfig, params: dict[str, Any]) -> Iterator[list[dict[str, Any]]]:
    """Fan calls/messages out over the conversations list.

    Quo requires `phoneNumberId` and `participants` on every calls/messages request, and the
    conversations list is the only endpoint that enumerates both. Each (phone number,
    participants) pair is queried once; a call or message belongs to exactly one such pair, so
    rows stay unique within a batch.
    """
    session = make_tracked_session(headers=_auth_headers(api_key), redact_values=(api_key,))
    conversations = QUO_ENDPOINTS["conversations"]
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for conversation_page in _paginate(session, conversations.path, {"maxResults": conversations.page_size}):
        for conversation in conversation_page:
            phone_number_id = conversation.get("phoneNumberId")
            participants = conversation.get("participants") or []
            if not phone_number_id or not participants:
                continue
            if not config.supports_group_conversations and len(participants) > 1:
                # /v1/calls serves one-to-one conversations only, so a group conversation's
                # calls cannot be listed. Skipping it beats a guaranteed 400 per group.
                continue
            pair = (phone_number_id, tuple(sorted(participants)))
            if pair in seen:
                continue
            seen.add(pair)
            # Repeated `participants` keys without brackets is the encoding Quo documents;
            # requests produces that for a list value.
            yield from _paginate(
                session, config.path, {**params, "phoneNumberId": phone_number_id, "participants": participants}
            )


def _rest_source(
    api_key: str,
    config: QuoEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[QuoResumeConfig],
    params: dict[str, Any],
    db_incremental_field_last_value: Optional[Any],
):
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": QUO_BASE_URL,
            "headers": {"Accept": "application/json"},
            # The framework auth redacts the key from logs. Quo's Authorization header carries
            # the raw key, which is exactly what api_key auth with the default name sends.
            "auth": {"type": "api_key", "api_key": api_key, "name": "Authorization", "location": "header"},
            # Also used for the endpoints documented as unpaginated: with no nextPageToken in the
            # body it stops after one page, and it follows the cursor if Quo ever adds one.
            "paginator": JSONResponseCursorPaginator(cursor_path="nextPageToken", cursor_param="pageToken"),
        },
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "data_selector": "data",
                    "params": params,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"cursor": resume.page_token}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; the state is saved after the page it covers
        # is yielded, so a crash re-yields that page and merge dedupes it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(QuoResumeConfig(page_token=str(state["cursor"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _source_response(endpoint: str, config: QuoEndpointConfig, items: Callable[[], Iterable[Any]]) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=[config.primary_key],
        # Quo lists return newest-first and the fan-out restarts per conversation, so rows never
        # arrive globally ascending. "desc" defers the watermark commit to the end of a
        # successful sync instead of checkpointing it mid-run.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def quo_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[QuoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = schema_for_resource(QUO_ENDPOINTS, endpoint)

    last_value = db_incremental_field_last_value if should_use_incremental_field else None
    cursor_field = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)
    params = _build_params(config, cursor_field, _to_iso(last_value))

    if config.fan_out_over_conversations:
        return _source_response(endpoint, config, lambda: _fan_out_rows(api_key, config, params))

    resource = _rest_source(
        api_key,
        config,
        team_id,
        job_id,
        resumable_source_manager,
        params,
        last_value,
    )
    return _source_response(endpoint, config, lambda: resource)
