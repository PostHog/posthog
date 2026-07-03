import re
import logging
import dataclasses
from collections.abc import Generator
from typing import Any
from urllib.parse import urlparse

from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    HTTPError,
    RequestException,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

logger = logging.getLogger(__name__)

# Convex deployments are served behind Cloudflare, which surfaces transient edge/origin
# problems as the 52x family (520 Unknown Error, 521 Web Server Down, 522 Connection Timed
# Out, 523 Origin Unreachable, 524 Timeout). These are retryable just like the standard 5xx
# codes, but urllib3's default forcelist doesn't include them — so a single transient 520
# would otherwise fail the whole sync. All Convex requests are idempotent GETs, so retrying
# them is safe. Derive from DEFAULT_RETRY so backoff/total/allowed-methods stay in sync.
_CLOUDFLARE_TRANSIENT_STATUSES = frozenset({520, 521, 522, 523, 524})
_CONVEX_RETRY = DEFAULT_RETRY.new(
    status_forcelist=frozenset(DEFAULT_RETRY.status_forcelist) | _CLOUDFLARE_TRANSIENT_STATUSES
)


# list_snapshot cursors are opaque {tablet, id} strings; document_deltas cursors are integer
# `_ts` timestamps. The two are not interchangeable, so each endpoint's resume state is kept
# under its own Redis namespace (see convex_source) to stop a retry that flips between them
# from replaying one endpoint's cursor against the other.
_SNAPSHOT_RESUME_NAMESPACE = "list_snapshot"
_DELTAS_RESUME_NAMESPACE = "document_deltas"


@dataclasses.dataclass
class ConvexResumeConfig:
    cursor: int | str
    snapshot: int | None = None


_CONVEX_CLOUD_HOST_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)?\.convex\.cloud$")


class InvalidDeployUrlError(Exception):
    """Raised when the deploy URL does not meet Convex security requirements."""

    pass


def validate_deploy_url(deploy_url: str) -> str:
    """Validate and normalize a Convex deployment URL.

    Enforces https scheme, host matching *.convex.cloud, no query/fragment.
    Returns the validated base URL (scheme + host, no trailing slash).
    """
    deploy_url = deploy_url.strip()
    # Tolerate a missing scheme — users routinely paste the bare host. We only add
    # https when no scheme is present; an explicit http:// is still rejected below.
    if deploy_url and "://" not in deploy_url:
        deploy_url = f"https://{deploy_url}"

    parsed = urlparse(deploy_url)

    if parsed.scheme != "https":
        raise InvalidDeployUrlError(
            "Deployment URL must use the https scheme (e.g. https://your-deployment-123.convex.cloud)."
        )

    host = (parsed.hostname or "").lower()
    if not host or not _CONVEX_CLOUD_HOST_RE.match(host):
        raise InvalidDeployUrlError(
            f"Deployment URL host must match <deployment-name>.convex.cloud or "
            f"<deployment-name>.<region>.convex.cloud, got: {host!r}."
        )

    if parsed.query:
        raise InvalidDeployUrlError("Deployment URL must not contain query parameters.")

    if parsed.fragment:
        raise InvalidDeployUrlError("Deployment URL must not contain a URL fragment.")

    return f"https://{host}"


def _headers(deploy_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Convex {deploy_key}",
        "Content-Type": "application/json",
    }


def get_json_schemas(deploy_url: str, deploy_key: str) -> dict[str, Any]:
    url = f"{deploy_url.rstrip('/')}/api/json_schemas"
    response = make_tracked_session(retry=_CONVEX_RETRY).get(
        url, headers=_headers(deploy_key), params={"deltaSchema": "true", "format": "json"}, timeout=30
    )
    response.raise_for_status()
    return response.json()


def list_snapshot(
    deploy_url: str,
    deploy_key: str,
    table_name: str,
    resumable_source_manager: ResumableSourceManager[ConvexResumeConfig],
) -> Generator[list[dict[str, Any]], None, int]:
    """Paginate through a full table snapshot.

    Yields batches of documents. Returns the snapshot cursor (as the generator return value)
    which can be used as the starting cursor for document_deltas.
    """
    base_url = f"{deploy_url.rstrip('/')}/api/list_snapshot"
    # Convex returns the snapshot cursor as an opaque {tablet, id} string, not an integer.
    cursor: int | str | None = None
    snapshot: int | None = None

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        cursor = resume_config.cursor
        snapshot = resume_config.snapshot

    while True:
        params: dict[str, Any] = {"tableName": table_name, "format": "json"}
        if cursor is not None:
            params["cursor"] = cursor
        if snapshot is not None:
            params["snapshot"] = snapshot

        response = make_tracked_session(retry=_CONVEX_RETRY).get(
            base_url, headers=_headers(deploy_key), params=params, timeout=60
        )
        response.raise_for_status()
        data = response.json()

        values = data.get("values", [])
        if values:
            yield values

        snapshot = data.get("snapshot", snapshot)
        cursor = data.get("cursor")
        has_more = data.get("hasMore", False)

        if not has_more:
            return snapshot or 0

        if cursor is not None:
            resumable_source_manager.save_state(ConvexResumeConfig(cursor=cursor, snapshot=snapshot))


class InvalidWindowError(Exception):
    """Raised when the delta cursor is older than Convex's retention window."""

    pass


def document_deltas(
    deploy_url: str,
    deploy_key: str,
    table_name: str,
    cursor: int,
    resumable_source_manager: ResumableSourceManager[ConvexResumeConfig],
) -> Generator[list[dict[str, Any]], None, int]:
    """Paginate through incremental document changes since a cursor.

    Yields batches of changed documents. Returns the new cursor.
    Deleted documents have _deleted=True.

    Raises InvalidWindowError if the cursor is older than Convex's retention window (~30 days).
    """
    base_url = f"{deploy_url.rstrip('/')}/api/document_deltas"
    current_cursor = cursor

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    # Only trust an integer resume cursor — document_deltas requires an integer `_ts`. A
    # non-integer here means stale or cross-endpoint state; ignore it and restart from the
    # DB watermark rather than replaying a cursor Convex would reject with a 400.
    if resume_config is not None:
        if isinstance(resume_config.cursor, int):
            current_cursor = resume_config.cursor
        else:
            # Namespacing should keep this from happening; if it does, surface it rather than
            # silently dropping the saved cursor.
            logger.warning(
                "Discarding non-integer document_deltas resume cursor for table '%s'; restarting from the DB watermark",
                table_name,
            )

    while True:
        params: dict[str, Any] = {"tableName": table_name, "cursor": current_cursor, "format": "json"}

        response = make_tracked_session(retry=_CONVEX_RETRY).get(
            base_url, headers=_headers(deploy_key), params=params, timeout=60
        )

        if response.status_code == 400:
            error_data = response.json()
            if error_data.get("code") == "InvalidWindowToReadDocuments":
                raise InvalidWindowError(
                    f"Delta cursor for table '{table_name}' is older than Convex's ~30 day retention window. "
                    f"Please trigger a full resync of this source."
                )
        response.raise_for_status()
        data = response.json()

        values = data.get("values", [])
        if values:
            yield values

        current_cursor = data.get("cursor", current_cursor)
        has_more = data.get("hasMore", False)

        if not has_more:
            return current_cursor

        resumable_source_manager.save_state(ConvexResumeConfig(cursor=current_cursor))


def validate_credentials(deploy_url: str, deploy_key: str) -> tuple[bool, str | None]:
    try:
        clean_url = validate_deploy_url(deploy_url)
    except InvalidDeployUrlError as e:
        return False, str(e)
    try:
        get_json_schemas(clean_url, deploy_key)
        return True, None
    except HTTPError as e:
        if e.response is not None:
            try:
                error_data = e.response.json()
                if error_data.get("code") == "StreamingExportNotEnabled":
                    return (
                        False,
                        "Streaming export requires the Convex Professional plan. See https://www.convex.dev/plans to upgrade.",
                    )
            except Exception:
                pass
            if e.response.status_code in (401, 403):
                return False, "Invalid deploy key. Check your Convex deploy key and try again."
        return False, str(e)
    except RequestsConnectionError:
        return False, "Could not connect to the Convex deployment. Check your deployment URL and try again."
    except RequestException as e:
        return False, str(e)


def _normalize_timestamps(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in batch:
        creation_time = row.get("_creationTime")
        if isinstance(creation_time, (int, float)) and creation_time > 1e12:
            row["_creationTime"] = int(creation_time / 1000)
    return batch


def convex_source(
    deploy_url: str,
    deploy_key: str,
    table_name: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any | None,
    resumable_source_manager: ResumableSourceManager[ConvexResumeConfig],
) -> SourceResponse:
    clean_url = validate_deploy_url(deploy_url)

    def items_generator():
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            cursor = int(db_incremental_field_last_value)
            deltas_manager = resumable_source_manager.with_namespace(_DELTAS_RESUME_NAMESPACE)
            for batch in document_deltas(clean_url, deploy_key, table_name, cursor, deltas_manager):
                yield _normalize_timestamps(batch)
        else:
            snapshot_manager = resumable_source_manager.with_namespace(_SNAPSHOT_RESUME_NAMESPACE)
            for batch in list_snapshot(clean_url, deploy_key, table_name, snapshot_manager):
                yield _normalize_timestamps(batch)

    return SourceResponse(
        name=table_name,
        items=items_generator,
        primary_keys=["_id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=["_creationTime"],
    )
