import re
import logging
from collections.abc import Generator
from typing import Any, ClassVar, NoReturn
from urllib.parse import urlparse

from requests import Response
from requests.exceptions import (
    ChunkedEncodingError,
    ConnectionError as RequestsConnectionError,
    HTTPError,
    ReadTimeout,
    RequestException,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.models.external_data_schema import update_sync_type_config_keys
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse

logger = logging.getLogger(__name__)

# Data sync and cursor conversion are read-only POSTs, so the GET retry policy is safe for them.
_CONVEX_RETRY = DEFAULT_RETRY.new(allowed_methods=frozenset(DEFAULT_RETRY.allowed_methods or ()) | {"POST"})
_DATA_SYNC_RESUME_NAMESPACE = "data_sync"
_SNAPSHOT_RESUME_NAMESPACE = "list_snapshot"


@frozen
class ConvexDataSyncCursor:
    cursor_kind: ClassVar[str] = "convex_data_sync"
    cursor: str


@frozen
class ConvexResumeConfig:
    # Shared by both read paths, which keep their state in separate namespaces: `list_snapshot`
    # uses `cursor` and `snapshot`, and the data sync uses `cursor` and `started_from_cursor`.
    cursor: int | str
    snapshot: int | None = None
    started_from_cursor: bool = False


_CONVEX_CLOUD_HOST_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)?\.convex\.cloud$")
# Production and development deploy keys name their deployment, e.g. "prod:swift-lemur-123|...".
_DEPLOY_KEY_DEPLOYMENT_RE = re.compile(r"^(?:prod|dev):([a-z0-9][a-z0-9-]*)\|")


class InvalidDeployUrlError(Exception):
    """Raised when the deploy URL does not meet Convex security requirements."""

    pass


def validate_deploy_url(deploy_url: str) -> str:
    """Validate and normalize a Convex deployment URL.

    Enforces https scheme, host matching *.convex.cloud, no query/fragment.
    Returns the validated base URL (scheme + host, no trailing slash).
    """
    deploy_url = deploy_url.strip()
    # Tolerate a missing scheme because users routinely paste the bare host. We only add
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


class InvalidDeployKeyError(Exception):
    """Raised when the deploy key cannot be sent in an Authorization header."""

    pass


def validate_deploy_key(deploy_key: str) -> str:
    """Validate and normalize a Convex deploy key.

    Returns the key without surrounding whitespace.
    """
    deploy_key = deploy_key.strip()

    if not deploy_key:
        raise InvalidDeployKeyError("Enter your Convex deploy key.")

    try:
        # http.client encodes header values as latin-1, so a character outside that range
        # aborts the request with a UnicodeEncodeError raised from inside urllib3. That error
        # names a codec and a string offset, so neither the user nor error tracking can tell
        # which field is at fault. Copying a key out of a browser can pick up such a character,
        # so reject it here with a message the user can act on.
        deploy_key.encode("latin-1")
    except UnicodeEncodeError:
        raise InvalidDeployKeyError(
            "Your deploy key contains characters PostHog can't send to Convex. "
            "Copy the key again from your Convex dashboard, then try again."
        ) from None

    return deploy_key


def deploy_key_targets_other_deployment(clean_url: str, deploy_key: str) -> bool:
    match = _DEPLOY_KEY_DEPLOYMENT_RE.match(deploy_key)
    if match is None:
        return False
    deployment_name = (urlparse(clean_url).hostname or "").split(".")[0]
    return match.group(1) != deployment_name


def _headers(deploy_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Convex {validate_deploy_key(deploy_key)}",
        "Content-Type": "application/json",
    }


# Convex tables can live in non-default components (e.g. an installed `betterAuth` component), which
# the export API addresses by component path (the root component is the empty path). We
# encode `(component_path, table)` into one warehouse table name so component tables round-trip from
# the schema list back to the per-table API calls; root tables keep their bare name, so existing
# synced tables are unaffected.
_ROOT_COMPONENT = ""
_COMPONENT_TABLE_DELIMITER = "."


@retry(
    # Mid-stream connection failures happen after headers, outside urllib3's retry handling.
    retry=retry_if_exception_type((ChunkedEncodingError, ReadTimeout, RequestsConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _convex_get(url: str, deploy_key: str, params: dict[str, Any], timeout: int) -> Response:
    return make_tracked_session(retry=_CONVEX_RETRY).get(
        url, headers=_headers(deploy_key), params=params, timeout=timeout
    )


@retry(
    retry=retry_if_exception_type((ChunkedEncodingError, ReadTimeout, RequestsConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _convex_post(url: str, deploy_key: str, body: dict[str, Any]) -> Response:
    return make_tracked_session(retry=_CONVEX_RETRY).post(url, headers=_headers(deploy_key), json=body, timeout=60)


class StreamingExportNotEnabledError(Exception):
    """Raised when the Convex deployment's plan doesn't include streaming export access."""

    pass


def get_json_schemas(deploy_url: str, deploy_key: str) -> dict[str, Any]:
    url = f"{deploy_url.rstrip('/')}/api/json_schemas"
    # byComponent=true groups the response by component so non-default components are discoverable.
    response = _convex_get(
        url, deploy_key, {"deltaSchema": "true", "format": "json", "byComponent": "true"}, timeout=30
    )
    if response.status_code == 400:
        try:
            error_data = response.json()
        except ValueError:
            error_data = {}
        # A plain HTTPError's message never carries the response body, so without this the
        # StreamingExportNotEnabled entry in get_non_retryable_errors can never match here -
        # it only matched by accident via validate_credentials' own body parsing below.
        if error_data.get("code") == "StreamingExportNotEnabled":
            raise StreamingExportNotEnabledError(
                "StreamingExportNotEnabled: streaming export requires the Convex Professional plan."
            )
    response.raise_for_status()
    return response.json()


def iter_component_tables(schemas_response: dict[str, Any]) -> Generator[tuple[str, str]]:
    """Yield `(component_path, table_name)` for every table; root tables yield `""`.

    `byComponent=true` groups as {component_path: {table: schema}}; older deployments ignore the flag
    and return the flat {table: schema} shape, where each value is itself a JSON schema.
    """
    if not isinstance(schemas_response, dict) or not schemas_response:
        return
    # The grouped shape always includes the root component under the "" key, and "" is never a valid
    # table name, so its presence reliably marks the grouped shape. Only when it's absent do we fall
    # back to inspecting the first value (a {table: schema} map carries no "type"/"properties").
    if _ROOT_COMPONENT in schemas_response:
        grouped = True
    else:
        first_value = next(iter(schemas_response.values()))
        grouped = isinstance(first_value, dict) and "type" not in first_value and "properties" not in first_value
    if grouped:
        for component_path, tables in schemas_response.items():
            if isinstance(tables, dict):
                for table_name in tables:
                    yield component_path, table_name
    else:
        for table_name in schemas_response:
            yield _ROOT_COMPONENT, table_name


def qualified_table_name(component_path: str, table_name: str) -> str:
    """Encode a `(component_path, table_name)` pair into a single warehouse table name."""
    if not component_path:
        return table_name
    return f"{component_path}{_COMPONENT_TABLE_DELIMITER}{table_name}"


def split_qualified_table_name(name: str) -> tuple[str, str]:
    """Inverse of `qualified_table_name`. Returns `(component_path, table_name)`.

    Splits on the final ".": component path segments join with "/" and table names contain no ".".
    """
    component_path, delimiter, table_name = name.rpartition(_COMPONENT_TABLE_DELIMITER)
    if not delimiter:
        return _ROOT_COMPONENT, name
    return component_path, table_name


class ConvexResyncRequiredError(Exception):
    pass


def _request_full_resync(
    inputs: SourceInputs, manager: ResumableSourceManager[ConvexResumeConfig], reason: str
) -> NoReturn:
    update_sync_type_config_keys(inputs.schema_id, inputs.team_id, updates={"reset_pipeline": True})
    manager.clear_state()
    logger.warning("Requesting a full Convex resync for table '%s': %s", inputs.schema_name, reason)
    raise ConvexResyncRequiredError(f"Convex full resync requested: {reason}. The next attempt will rebuild the table.")


def _normalize_timestamps(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in batch:
        creation_time = row.get("_creationTime")
        if isinstance(creation_time, (int, float)) and creation_time > 1e12:
            row["_creationTime"] = int(creation_time / 1000)
    return batch


def data_sync(
    deploy_url: str,
    deploy_key: str,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[ConvexResumeConfig],
    cursor_manager: SourceCursorManager[ConvexDataSyncCursor],
) -> Generator[list[dict[str, Any]]]:
    component, table = split_qualified_table_name(inputs.schema_name)
    selection = {"_other": "excluded", component: {"_other": "excluded", table: {"_other": "included"}}}
    manager = resumable_source_manager.with_namespace(_DATA_SYNC_RESUME_NAMESPACE)
    resume = manager.load_state() if manager.can_resume() else None
    stored = cursor_manager.load() if inputs.should_use_incremental_field else None
    cursor = stored.cursor if stored is not None else None
    started_from_cursor = cursor is not None

    if resume is not None:
        if not isinstance(resume.cursor, str):
            raise ValueError("Convex data sync resume state has an invalid cursor")
        cursor = resume.cursor
        started_from_cursor = resume.started_from_cursor
        logger.info("Resuming an in-run Convex data sync for table '%s'", inputs.schema_name)
    elif started_from_cursor:
        logger.info("Starting Convex data sync from a stored cursor for table '%s'", inputs.schema_name)
    elif inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
        try:
            response = _convex_post(
                f"{deploy_url}/api/data_sync_cursor_from_deltas",
                deploy_key,
                {"cursor": int(inputs.db_incremental_field_last_value), "selection": selection},
            )
            response.raise_for_status()
            cursor = response.json()["cursor"]
            if not isinstance(cursor, str) or not cursor:
                raise ValueError("Convex cursor conversion returned no cursor")
        except HTTPError as e:
            # Only Convex refusing the conversion (an old backend, or a watermark past retention) means
            # the position is gone. A 429 or 5xx is transient: retry rather than resync every table.
            status = e.response.status_code if e.response is not None else None
            if status is None or not 400 <= status < 500 or status == 429:
                raise
            logger.warning("Convex refused the legacy watermark conversion for table '%s'", inputs.schema_name)
            _request_full_resync(inputs, manager, "the legacy sync position could not be converted")
        except (KeyError, TypeError, ValueError):
            logger.warning("Convex returned an unusable cursor conversion for table '%s'", inputs.schema_name)
            _request_full_resync(inputs, manager, "the legacy sync position could not be converted")
        started_from_cursor = True
        logger.info("Converted the Convex legacy watermark for table '%s' without a resync", inputs.schema_name)
        # No rows are pending, so persist the converted cursor before a retry can repeat the migration.
        with manager.committing():
            manager.save_state(ConvexResumeConfig(cursor=cursor, started_from_cursor=True))
    else:
        logger.info("Starting a fresh Convex data sync for table '%s'", inputs.schema_name)

    while True:
        body: dict[str, Any] = {"selection": selection}
        if cursor is not None:
            body["cursor"] = cursor
        response = _convex_post(f"{deploy_url}/api/v1/data/sync", deploy_key, body)
        if response.status_code == 400:
            try:
                error_data = response.json()
            except ValueError:
                error_data = {}
            if error_data.get("code") == "DataSyncCursorExpired":
                _request_full_resync(inputs, manager, "the Convex data sync cursor has expired")
            if error_data.get("code") == "StreamingExportNotEnabled":
                raise StreamingExportNotEnabledError(
                    "StreamingExportNotEnabled: streaming export requires the Convex Professional plan."
                )
        response.raise_for_status()
        page = response.json()
        if started_from_cursor and any(
            truncate["component"] == component and truncate["table"] == table for truncate in page["truncates"]
        ):
            _request_full_resync(inputs, manager, "the table was replaced in Convex")

        next_cursor = page["pagination"]["nextCursor"]
        if not isinstance(next_cursor, str) or not next_cursor:
            raise ValueError("Convex data sync response is missing a cursor")
        # A document can appear at several revisions in one page, in increasing `ts` order. Keep the
        # last so a merge on `_id` never sees two source rows for one target row.
        latest: dict[str, dict[str, Any]] = {}
        for entry in page["values"]:
            row = {**entry["value"], "_ts": entry["ts"], "_deleted": entry["deleted"]}
            latest[row["_id"]] = row
        rows = list(latest.values())
        if rows:
            yield _normalize_timestamps(rows)

        cursor = next_cursor
        manager.save_state(ConvexResumeConfig(cursor=cursor, started_from_cursor=started_from_cursor))
        manager.safe_point()
        # This infinite stream always has more pages; the status says when the current run has caught up.
        if page["status"]["type"] == "upToDate":
            if inputs.should_use_incremental_field:
                cursor_manager.stage(ConvexDataSyncCursor(cursor=cursor))
            return


def list_snapshot(
    deploy_url: str,
    deploy_key: str,
    table_name: str,
    resumable_source_manager: ResumableSourceManager[ConvexResumeConfig],
    component: str = _ROOT_COMPONENT,
) -> Generator[list[dict[str, Any]]]:
    """Read one consistent snapshot of a table, each document exactly once.

    Full-refresh runs use this legacy endpoint rather than the data sync: a fresh data sync emits a
    document again at each revision it reaches while catching up, and full-refresh loads append
    batches instead of merging them on `_id`.
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
        if component:
            params["component"] = component
        if cursor is not None:
            params["cursor"] = cursor
        if snapshot is not None:
            params["snapshot"] = snapshot

        response = _convex_get(base_url, deploy_key, params, timeout=60)
        response.raise_for_status()
        data = response.json()

        values = data.get("values", [])
        if values:
            yield values

        snapshot = data.get("snapshot", snapshot)
        cursor = data.get("cursor")
        if not data.get("hasMore", False):
            return

        if cursor is not None:
            resumable_source_manager.save_state(ConvexResumeConfig(cursor=cursor, snapshot=snapshot))
            resumable_source_manager.safe_point()


def validate_credentials(deploy_url: str, deploy_key: str) -> tuple[bool, str | None]:
    try:
        clean_url = validate_deploy_url(deploy_url)
        deploy_key = validate_deploy_key(deploy_key)
    except (InvalidDeployUrlError, InvalidDeployKeyError) as e:
        return False, str(e)
    try:
        get_json_schemas(clean_url, deploy_key)
        return True, None
    except StreamingExportNotEnabledError:
        return (
            False,
            "Streaming export requires the Convex Professional plan. See https://www.convex.dev/plans to upgrade.",
        )
    except HTTPError as e:
        if e.response is not None:
            if e.response.status_code in (401, 403):
                if deploy_key_targets_other_deployment(clean_url, deploy_key):
                    return (
                        False,
                        "Your deploy key belongs to a different Convex deployment than your deployment URL. "
                        "Copy both from the same deployment's settings, then reconnect.",
                    )
                return (
                    False,
                    "Convex rejected your deploy key. Copy a new deploy key from your Convex dashboard, then reconnect.",
                )
        # Any other status falls through to a generic message. Keep the raw error
        # (which embeds the deployment URL) out of what the user sees.
        detail = f" (HTTP {e.response.status_code})" if e.response is not None else ""
        return (
            False,
            f"The Convex deployment rejected the request{detail}. Check your deployment URL and deploy key, then try again.",
        )
    except RequestsConnectionError:
        return False, "Could not connect to the Convex deployment. Check your deployment URL and try again."
    except RequestException as e:
        return False, str(e)


def convex_source(
    deploy_url: str,
    deploy_key: str,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[ConvexResumeConfig],
    cursor_manager: SourceCursorManager[ConvexDataSyncCursor],
) -> SourceResponse:
    clean_url = validate_deploy_url(deploy_url)

    def items_generator() -> Generator[list[dict[str, Any]]]:
        if inputs.should_use_incremental_field:
            yield from data_sync(clean_url, deploy_key, inputs, resumable_source_manager, cursor_manager)
            return
        component, table = split_qualified_table_name(inputs.schema_name)
        snapshot_manager = resumable_source_manager.with_namespace(_SNAPSHOT_RESUME_NAMESPACE)
        for batch in list_snapshot(clean_url, deploy_key, table, snapshot_manager, component=component):
            yield _normalize_timestamps(batch)

    return SourceResponse(
        name=inputs.schema_name,
        items=items_generator,
        primary_keys=["_id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=["_creationTime"],
    )
