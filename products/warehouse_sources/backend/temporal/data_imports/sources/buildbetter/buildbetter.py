import re
import dataclasses
from collections.abc import Callable, Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.queries import (
    OPTIONAL_QUERY_FIELDS,
    QUERIES,
    VIEWER_QUERY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildbetter.settings import (
    BUILDBETTER_API_URL,
    BUILDBETTER_API_VERSION_V3,
    BUILDBETTER_ENDPOINTS,
    BUILDBETTER_REST_API_URL,
    BUILDBETTER_REST_PAGE_SIZE,
    BUILDBETTER_V3_REST_PRIMARY_KEYS,
    CREATED_AT,
    INTERVIEW_CREATED_AT,
    INTERVIEW_ID,
    INTERVIEW_UPDATED_AT,
    SENTENCE_INDEX,
    SPEAKER,
    UPDATED_AT,
    BuildBetterEndpointConfig,
    BuildBetterNestedConfig,
    uses_rest_api,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

_MISSING_FIELD_RE = re.compile(r"field '([^']+)' not found in type")


class BuildBetterRetryableError(Exception):
    pass


class BuildBetterMissingFieldError(Exception):
    def __init__(self, field_name: str) -> None:
        self.field_name = field_name
        super().__init__(field_name)


@dataclasses.dataclass(frozen=True)
class BuildBetterResumeConfig:
    offset: int = 0
    # The REST API pages by page number rather than offset
    page: int | None = None


def _make_session(api_key: str) -> requests.Session:
    return make_tracked_session(
        headers={
            "X-Buildbetter-API-Key": api_key,
            "Content-Type": "application/json",
        }
    )


def _resolve_endpoint(endpoint_name: str) -> tuple[BuildBetterEndpointConfig, str]:
    endpoint_config = BUILDBETTER_ENDPOINTS.get(endpoint_name)
    if not endpoint_config:
        raise ValueError(f"Unknown BuildBetter endpoint: {endpoint_name}")

    query = QUERIES.get(endpoint_name)
    if not query:
        raise ValueError(f"No GraphQL query for endpoint: {endpoint_name}")

    return endpoint_config, query


def _raise_for_retryable_status(response: requests.Response) -> None:
    if response.status_code >= 500:
        raise BuildBetterRetryableError(f"BuildBetter: server error {response.status_code}")

    if response.status_code == 429:
        raise BuildBetterRetryableError("BuildBetter: rate limited")


def _decode_payload(response: requests.Response) -> dict:
    try:
        return response.json()
    except Exception:
        if not response.ok:
            raise Exception(
                f"{response.status_code} Client Error: {response.reason} (BuildBetter API: {response.text})"
            )
        raise Exception(f"Unexpected BuildBetter response: {response.text}")


def _raise_for_payload_errors(response: requests.Response, payload: dict, droppable_fields: dict[str, str]) -> None:
    if "errors" in payload:
        error_messages = [e.get("message", "") for e in payload["errors"]]
        joined = "; ".join(error_messages)
        if not response.ok:
            raise Exception(f"{response.status_code} Client Error: {response.reason} (BuildBetter API: {joined})")
        for msg in error_messages:
            match = _MISSING_FIELD_RE.search(msg)
            if match and (field := match.group(1)) in droppable_fields:
                raise BuildBetterMissingFieldError(field)
        raise Exception(f"BuildBetter GraphQL error: {joined}")

    if not response.ok:
        raise Exception(f"{response.status_code} Client Error: {response.reason} (BuildBetter API: {payload})")

    if "data" not in payload:
        raise Exception(f"Unexpected BuildBetter response format. Keys: {list(payload.keys())}")


@retry(
    retry=retry_if_exception_type(BuildBetterRetryableError),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _execute_query(
    sess: requests.Session,
    query: str,
    variables: dict[str, Any],
    droppable_fields: dict[str, str],
) -> dict:
    response = sess.post(BUILDBETTER_API_URL, json={"query": query, "variables": variables}, timeout=60)

    _raise_for_retryable_status(response)
    payload = _decode_payload(response)
    _raise_for_payload_errors(response, payload, droppable_fields)

    return payload


def _nested_items(nested: BuildBetterNestedConfig, parent: dict) -> list[dict]:
    value = parent.get(nested.nested_field)
    if not nested.single:
        return value or []
    return [{f"{nested.unwrap_prefix}{key}": item for key, item in value.items()}] if value else []


def _flatten_nested_rows(nested: BuildBetterNestedConfig, parent_rows: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for parent in parent_rows:
        parent_columns = {column: parent.get(parent_field) for parent_field, column in nested.parent_columns.items()}
        for index, child in enumerate(_nested_items(nested, parent)):
            row = dict(child)
            if nested.unwrap_field:
                inner = row.pop(nested.unwrap_field, None)
                if not inner:
                    # Without the wrapped record the row has no key columns to merge on
                    continue
                row = {f"{nested.unwrap_prefix}{key}": value for key, value in inner.items()} | row
            if nested.index_column:
                row[nested.index_column] = index
            rows.append(parent_columns | row)
    return rows


def _filter_field(endpoint_config: BuildBetterEndpointConfig, incremental_field: str) -> str:
    """Map a row's incremental column back to the field the filter applies to.

    A nested table's rows carry the parent's timestamps under a prefixed column name, but the
    `where` clause filters the parent query, which knows them by their own names.
    """
    nested = endpoint_config.nested
    if nested is None:
        return incremental_field

    for parent_field, column in nested.parent_columns.items():
        if column == incremental_field:
            return parent_field
    return incremental_field


def _initial_variables(
    endpoint_name: str,
    endpoint_config: BuildBetterEndpointConfig,
    page_size: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BuildBetterResumeConfig],
    incremental_field: str | None,
    incremental_field_last_value: str | None,
) -> dict[str, Any]:
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_offset = resume_config.offset if resume_config is not None else 0
    if resume_config is not None:
        logger.debug(f"BuildBetter: resuming {endpoint_name} from offset {initial_offset}")

    variables: dict[str, Any] = {
        "limit": page_size,
        "offset": initial_offset,
    }

    if incremental_field and incremental_field_last_value:
        variables["where"] = {_filter_field(endpoint_config, incremental_field): {"_gt": incremental_field_last_value}}

    return variables


def _make_paginated_request(
    api_key: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BuildBetterResumeConfig],
    incremental_field: str | None = None,
    incremental_field_last_value: str | None = None,
):
    endpoint_config, query = _resolve_endpoint(endpoint_name)

    # Nested fields still present in the query that we will drop if the account's schema rejects them.
    droppable_fields = dict(OPTIONAL_QUERY_FIELDS.get(endpoint_name, {}))

    graphql_query_name = endpoint_config.graphql_query_name or endpoint_name
    page_size = endpoint_config.page_size

    sess = _make_session(api_key)

    variables = _initial_variables(
        endpoint_name=endpoint_name,
        endpoint_config=endpoint_config,
        page_size=page_size,
        logger=logger,
        resumable_source_manager=resumable_source_manager,
        incremental_field=incremental_field,
        incremental_field_last_value=incremental_field_last_value,
    )

    try:
        while True:
            logger.debug(f"Querying BuildBetter endpoint {endpoint_name} with variables: {variables}")
            try:
                payload = _execute_query(sess, query, variables, droppable_fields)
            except BuildBetterMissingFieldError as e:
                query = query.replace(droppable_fields.pop(e.field_name), "")
                logger.warning(
                    f"BuildBetter: field '{e.field_name}' not available for {endpoint_name}, retrying without it"
                )
                continue

            data = payload["data"][graphql_query_name]
            if not data:
                break

            rows = _flatten_nested_rows(endpoint_config.nested, data) if endpoint_config.nested else data
            if rows:
                yield rows

            if len(data) < page_size:
                break

            variables["offset"] = variables["offset"] + len(data)
            resumable_source_manager.save_state(BuildBetterResumeConfig(offset=variables["offset"]))
    finally:
        sess.close()


@retry(
    retry=retry_if_exception_type(BuildBetterRetryableError),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _rest_get(
    sess: requests.Session, path: str, params: dict[str, Any] | None = None, missing_ok: bool = False
) -> dict | None:
    response = sess.get(f"{BUILDBETTER_REST_API_URL}{path}", params=params, timeout=60)

    _raise_for_retryable_status(response)
    # A recording deleted between the list read and its detail read returns 404
    if missing_ok and response.status_code == 404:
        return None
    response.raise_for_status()

    return response.json()


def _recording_parent_columns(recording: dict) -> dict[str, Any]:
    return {
        INTERVIEW_ID: recording.get("id"),
        INTERVIEW_CREATED_AT: recording.get(CREATED_AT),
        INTERVIEW_UPDATED_AT: recording.get(UPDATED_AT),
    }


def _rest_attendee_rows(sess: requests.Session, recording: dict) -> list[dict]:
    detail = _rest_get(sess, f"/recordings/{recording['id']}", missing_ok=True)
    if detail is None:
        return []

    parent_columns = _recording_parent_columns(recording)
    return [
        parent_columns | {SPEAKER: participant.get("speaker"), "person": participant.get("person")}
        for participant in detail.get("participants") or []
    ]


def _rest_sentence_rows(sess: requests.Session, recording: dict) -> list[dict]:
    transcript = _rest_get(sess, f"/recordings/{recording['id']}/transcript", {"type": "utterance"}, missing_ok=True)
    if transcript is None:
        return []

    parent_columns = _recording_parent_columns(recording)
    return [
        parent_columns
        | {
            "text": utterance.get("text"),
            SPEAKER: utterance.get("speaker"),
            "start_sec": utterance.get("startSec"),
            "end_sec": utterance.get("endSec"),
            SENTENCE_INDEX: index,
        }
        for index, utterance in enumerate(transcript.get("utterances") or [])
    ]


_REST_CHILD_ROWS: dict[str, Callable[[requests.Session, dict], list[dict]]] = {
    "interview_attendees": _rest_attendee_rows,
    "interview_sentences": _rest_sentence_rows,
}


def _make_rest_paginated_request(
    api_key: str,
    endpoint_name: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BuildBetterResumeConfig],
) -> Iterator[list[dict]]:
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume_config.page if resume_config is not None and resume_config.page is not None else 1
    if page > 1:
        logger.debug(f"BuildBetter: resuming {endpoint_name} from page {page}")

    child_rows = _REST_CHILD_ROWS.get(endpoint_name)
    sess = _make_session(api_key)

    try:
        while True:
            payload = _rest_get(sess, "/recordings", {"page": page, "limit": BUILDBETTER_REST_PAGE_SIZE}) or {}
            recordings = payload.get("recordings") or []

            if child_rows is None:
                rows = recordings
            else:
                rows = [row for recording in recordings for row in child_rows(sess, recording)]

            has_more = bool(recordings) and bool(payload.get("has_more"))
            if has_more:
                resumable_source_manager.save_state(BuildBetterResumeConfig(page=page + 1))
            if rows:
                yield rows

            if not has_more:
                break
            page += 1
    finally:
        sess.close()


def buildbetter_source(
    api_key: str,
    endpoint_name: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BuildBetterResumeConfig],
    incremental_field: str | None = None,
    incremental_field_last_value: str | None = None,
) -> SourceResponse:
    endpoint_config = BUILDBETTER_ENDPOINTS.get(endpoint_name)
    if not endpoint_config:
        raise ValueError(f"Unknown BuildBetter endpoint: {endpoint_name}")

    use_rest = uses_rest_api(endpoint_name, api_version)

    def get_rows():
        if use_rest:
            yield from _make_rest_paginated_request(
                api_key=api_key,
                endpoint_name=endpoint_name,
                logger=logger,
                resumable_source_manager=resumable_source_manager,
            )
            return

        if incremental_field and incremental_field_last_value:
            logger.debug(
                f"BuildBetter: incremental sync for {endpoint_name} on {incremental_field} since {incremental_field_last_value}"
            )

        yield from _make_paginated_request(
            api_key=api_key,
            endpoint_name=endpoint_name,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            incremental_field=incremental_field,
            incremental_field_last_value=incremental_field_last_value,
        )

    return SourceResponse(
        items=get_rows,
        primary_keys=BUILDBETTER_V3_REST_PRIMARY_KEYS[endpoint_name] if use_rest else endpoint_config.primary_keys,
        name=endpoint_name,
        partition_count=endpoint_config.partition_count,
        partition_size=endpoint_config.partition_size,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )


def validate_credentials(api_key: str, api_version: str) -> tuple[bool, str | None]:
    try:
        sess = _make_session(api_key)
        if api_version == BUILDBETTER_API_VERSION_V3:
            response = sess.get(f"{BUILDBETTER_REST_API_URL}/recordings", params={"page": 1, "limit": 1}, timeout=10)
            response.raise_for_status()
            if "recordings" in response.json():
                return True, None
            return False, "Could not verify BuildBetter credentials"

        response = sess.post(
            BUILDBETTER_API_URL,
            json={"query": VIEWER_QUERY},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            return False, f"BuildBetter API error: {data['errors']}"
        if "data" in data and data["data"].get("interview") is not None:
            return True, None
        return False, "Could not verify BuildBetter credentials"
    except Exception as e:
        return False, str(e)
