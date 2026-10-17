import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
import structlog
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.url_utils import redact_literal_values
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.expo.settings import EXPO_ENDPOINTS, build_query

EXPO_GRAPHQL_URL = "https://api.expo.dev/graphql"
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60

# Expo types `viewer` as `User`, so it does not resolve for robot or SSO user tokens.
# `meActor` returns the `Actor` interface, which covers every account type.
_ACTOR_QUERY = "query PostHogExpoActor { meActor { id } }"
_REJECTED_TOKEN_HINT = "Create a new one at expo.dev under Access tokens."
# `get_non_retryable_errors` in source.py matches sync errors that start with this prefix.
_API_ERROR_PREFIX = "Expo API error: "
_MAX_ERROR_DETAIL_CHARS = 200

logger = structlog.get_logger(__name__)


class ExpoAPIError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class ExpoResumeConfig:
    offset: int


def _get_session(access_token: str) -> requests.Session:
    return make_tracked_session(
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        redact_values=(access_token,),
    )


def _run_query(session: requests.Session, query: str, variables: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    response = session.post(
        EXPO_GRAPHQL_URL,
        json={"query": query, "variables": variables or {}},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    # GraphQL reports application errors in a 200 response, so status alone says nothing.
    errors = payload.get("errors")
    if errors:
        message = "; ".join(str(error.get("message", error)) for error in errors)
        raise ExpoAPIError(f"{_API_ERROR_PREFIX}{message}")
    return payload.get("data") or {}


def _error_detail(error: Exception, access_token: str) -> str:
    # Expo's error text goes into logs and into the message the user sees, so mask the token in case Expo echoes it.
    detail = redact_literal_values(str(error), (access_token,)).removeprefix(_API_ERROR_PREFIX)
    return detail[:_MAX_ERROR_DETAIL_CHARS].rstrip(".")


def validate_credentials(access_token: str, project_id: str) -> tuple[bool, Optional[str]]:
    session = _get_session(access_token)
    try:
        data = _run_query(session, _ACTOR_QUERY)
    except ExpoAPIError as error:
        detail = _error_detail(error, access_token)
        logger.warning("expo_source.validate_credentials_failed", cause="token_graphql_error", error=detail)
        return False, f"Expo rejected this access token ({detail}). {_REJECTED_TOKEN_HINT}"
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        logger.warning("expo_source.validate_credentials_failed", cause="token_http_error", status_code=status)
        if status in (401, 403):
            return False, f"Expo rejected this access token (HTTP {status}). {_REJECTED_TOKEN_HINT}"
        return False, f"Expo returned an unexpected error ({status}) while checking this access token."
    except Exception as error:
        logger.warning("expo_source.validate_credentials_failed", cause="token_unreachable", error=type(error).__name__)
        return False, "Could not reach the Expo API. Check your connection and try again."

    if not (data.get("meActor") or {}).get("id"):
        logger.warning("expo_source.validate_credentials_failed", cause="token_no_actor")
        return False, f"Expo did not return an account for this access token. {_REJECTED_TOKEN_HINT}"

    try:
        # A valid token still needs access to this specific project, so probe one row.
        project_data = _run_query(
            session,
            build_query("builds"),
            {"appId": project_id, "offset": 0, "limit": 1},
        )
        if (project_data.get("app") or {}).get("byId") is None:
            raise ExpoAPIError("Expo project not found")
    except (ExpoAPIError, requests.HTTPError) as error:
        logger.warning(
            "expo_source.validate_credentials_failed",
            cause="project_inaccessible",
            error=_error_detail(error, access_token),
        )
        return False, (
            "Expo could not read this project. Check the project ID, and that the token's account owns it. "
            "Run `eas project:info` to see the ID."
        )
    except Exception as error:
        logger.warning(
            "expo_source.validate_credentials_failed", cause="project_unreachable", error=type(error).__name__
        )
        return False, "Could not reach the Expo API. Check your connection and try again."

    return True, None


def get_rows(
    access_token: str,
    project_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ExpoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = EXPO_ENDPOINTS[endpoint]
    session = _get_session(access_token)
    query = build_query(endpoint)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume_config.offset if resume_config is not None else 0
    if resume_config is not None:
        logger.debug(f"Expo: resuming {endpoint} from offset {offset}")

    while True:
        data = _run_query(session, query, {"appId": project_id, "offset": offset, "limit": PAGE_SIZE})
        app = (data.get("app") or {}).get("byId")
        if app is None:
            raise ExpoAPIError("Expo project not found or inaccessible")
        items = app.get(config.collection) or []

        if items:
            yield items

        if len(items) < PAGE_SIZE:
            break

        offset += PAGE_SIZE
        # Saved after the batch is yielded: a crash re-reads the last page, which merge dedupes.
        resumable_source_manager.save_state(ExpoResumeConfig(offset=offset))


def expo_source(
    access_token: str,
    project_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ExpoResumeConfig],
) -> SourceResponse:
    config = EXPO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            project_id=project_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # EAS returns these collections newest first and offers no sort argument.
        sort_mode="desc",
    )
