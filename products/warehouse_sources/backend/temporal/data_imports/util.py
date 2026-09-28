import re
import time
import errno
import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from functools import wraps
from typing import Literal, Optional, ParamSpec, TypeVar
from uuid import uuid4

from django.conf import settings
from django.db import OperationalError as DjangoOperationalError

import psycopg
import botocore.exceptions
from structlog.types import FilteringBoundLogger

from posthog.exceptions import capture_exception
from posthog.settings.utils import get_from_env
from posthog.temporal.common.db_errors import is_transient_db_error
from posthog.temporal.common.errors import NonReportableError
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_stale_db_connections
from posthog.utils import str_to_bool

from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention

LOGGER = get_logger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

# A best-effort delete of old query folders can hit a transient S3 connectivity blip
# (connect/read timeout, dropped connection). The folder is timestamped and simply gets
# picked up by the age-based GC on a later sync, so these aren't worth an error-tracking
# issue - unlike a failure that needs a human (denied permissions, a storage backend with no
# free space), which still gets captured.
_TRANSIENT_S3_CONNECTION_EXCEPTIONS = (
    botocore.exceptions.ConnectionError,  # covers ConnectTimeoutError, EndpointConnectionError
    botocore.exceptions.ReadTimeoutError,
    botocore.exceptions.ConnectionClosedError,
)


def _is_transient_s3_connection_error(error: BaseException) -> bool:
    return isinstance(error, _TRANSIENT_S3_CONNECTION_EXCEPTIONS)


# s3fs turns an S3 error response into a Python exception by error code
# (``s3fs/errors.py::translate_boto_error``) and keeps the original ``ClientError`` on ``__cause__``.
# Every code S3 uses to ask a client to back off - ``SlowDown``, ``ServiceUnavailable``,
# ``OperationAborted`` and the bare 503/409 statuses - maps onto ``errno.EBUSY``, so the errno
# identifies "busy, come back later" without matching a vendor's free-text message. The code itself
# is read too, for a ``ClientError`` that reaches us untranslated.
_S3_THROTTLING_ERROR_CODES = frozenset({"SlowDown", "ServiceUnavailable", "OperationAborted", "503", "409"})


def _s3_error_code(error: BaseException) -> Optional[str]:
    client_error = error if isinstance(error, botocore.exceptions.ClientError) else error.__cause__
    if not isinstance(client_error, botocore.exceptions.ClientError):
        return None
    code = client_error.response.get("Error", {}).get("Code")
    return str(code) if code is not None else None


def _is_s3_throttling_error(error: BaseException) -> bool:
    """True when the object store refused the request to protect itself, rather than failing it.

    The same request succeeds once the rate drops, so the caller retries with backoff instead of
    reporting. Bulk operations hit this the hardest: one recursive delete of a query folder is a
    list plus a batched DeleteObjects against a single prefix, which is exactly the shape S3
    rate-limits.
    """
    if isinstance(error, OSError) and error.errno == errno.EBUSY:
        return True
    return _s3_error_code(error) in _S3_THROTTLING_ERROR_CODES


class S3OperationError(Exception):
    """An operation on PostHog's own data-warehouse bucket failed for a reason a retry cannot fix.

    Denied permissions and a storage backend out of free space both reach us as the raw s3fs text,
    which names our bucket, one team's folder and the object key. That text is not only logged: an
    activity failure we do not classify has its message stored as the ``latest_error`` a customer
    reads (``external_data_job.py::_customer_facing_error``), and it is also the title error
    tracking groups on, where a per-object message splits one condition across many issues. This
    error's message names the operation and the kind of path instead, and the original error stays
    on ``__cause__`` for the logs and the captured exception chain.

    Deliberately not a ``NonReportableError``: these conditions need a human, so they must still
    reach error tracking.
    """

    def __init__(self, operation: str, cause: BaseException) -> None:
        super().__init__(
            f"PostHog couldn't {operation}. The problem is in PostHog's own storage, not in "
            "your data. The next scheduled run will try again."
        )
        self.operation = operation
        # Set here rather than through ``raise ... from cause`` so a site that reports this error
        # without raising it keeps the original too.
        self.__cause__ = cause


class NonRetryableException(NonReportableError):
    """Raised only for errors already classified as a permanent customer/upstream condition
    (bad credentials, denied permissions, a deleted remote) via a source's
    ``get_non_retryable_errors`` or an equivalent shared-code check, never for a fresh,
    unclassified failure. Subclassing ``NonReportableError`` keeps that already-known condition
    out of error tracking instead of reporting it as a new bug on every occurrence."""

    @property
    def cause(self) -> Optional[BaseException]:
        """Cause of the exception.

        This is the same as ``Exception.__cause__``.
        """
        return self.__cause__


class PostHogInternalDatabaseError(Exception):
    """Raised when shared pipeline code fails to reach PostHog's own database.

    A transient connectivity blip reaching our database (e.g. a DNS hiccup resolving our
    host) stringifies with the same wording (e.g. "Name or service not known") a customer's
    misconfigured source host would produce. Sources' `get_non_retryable_errors` match on
    that wording to stop syncs against a permanently broken customer host, so this error's
    message intentionally avoids those substrings to keep it retryable instead of being
    misclassified as a permanent failure of the source being synced.
    """


# Transient failures reaching PostHog's own database, matched on the wording psycopg reports.
# `is_transient_db_error` deliberately leaves connect-time failures out, because it also classifies
# errors raised against a customer-supplied host, where a name that does not resolve or a port that
# refuses a connection is permanent misconfiguration. Code whose only database is ours reads the
# same wording the other way round: our host stops resolving, or refuses a connection, while
# infrastructure moves under a long-lived worker, and a later attempt reaches the database again.
# The list stays this narrow because psycopg reports a rejected password and a missing database
# through the same OperationalError class, and those must keep failing fast.
_TRANSIENT_INTERNAL_DB_MARKERS = (
    # Our host did not resolve. psycopg resolves the host itself and reports whatever
    # getaddrinfo returned, so which of these wordings arrives depends on how resolution failed
    # (EAI_NONAME, EAI_AGAIN, EAI_NODATA and EAI_FAIL respectively), and the last one is libpq's
    # equivalent. EAI_FAIL belongs here too: our host name comes from our own configuration, so a
    # resolver that answers "non-recoverable" is describing the resolver, not the name.
    "name or service not known",
    "temporary failure in name resolution",
    "no address associated with hostname",
    "non-recoverable failure in name resolution",
    "could not translate host name",
    # Nothing accepts a connection on the port, because the pooler or the database is restarting
    # or its endpoint is being re-pointed.
    "connection refused",
)

# The tightest start_to_close timeout among the activities that use this is one minute, so the
# retry budget has to stay well inside it. 4 attempts spend 14s on backoff (2+4+8s), and a failed
# attempt adds almost nothing because an unresolvable name and a refused port both fail at once.
_INTERNAL_DB_MAX_ATTEMPTS = 4


def is_transient_internal_db_error(error: BaseException) -> bool:
    """Whether `error` is a transient failure reaching PostHog's own database.

    Only for code that talks to our database. Never classify a connection to a customer's source
    database with this, because there the same psycopg wording means the customer's host is
    misconfigured and the sync has to stop instead of retrying.
    """
    if is_transient_db_error(error):
        return True
    if not isinstance(error, DjangoOperationalError | psycopg.OperationalError):
        return False
    message = str(error).lower()
    return any(marker in message for marker in _TRANSIENT_INTERNAL_DB_MARKERS)


def retry_internal_db_operation(operation: Callable[[], T]) -> T:
    """Run `operation`, and retry it with backoff while reaching PostHog's own database fails
    transiently.

    An activity that reads our database at its start fails through no fault of its own when the
    host briefly stops resolving or refuses a connection, and each failed attempt reports an
    exception nobody can action. Absorb the blip here, so only an exhausted budget reaches error
    tracking, where it describes a database that is really unreachable.

    `posthog.temporal.common.utils.retry_on_db_connection_drop` covers the neighboring case of a
    stale pooled connection, which one immediate retry on a fresh connection resolves. A connect
    failure needs the delay as well, because the name or the port has to become reachable first.

    Pass a zero-arg callable that produces the result, so a retry issues a fresh query:

        schema = retry_internal_db_operation(lambda: ExternalDataSchema.objects.get(id=schema_id))
    """
    attempt = 0

    while True:
        attempt += 1
        try:
            return operation()
        except Exception as e:
            if attempt >= _INTERNAL_DB_MAX_ATTEMPTS or not is_transient_internal_db_error(e):
                raise
            # A failed attempt can leave a broken connection in this worker's pool, so evict it
            # and let the next attempt reconnect.
            close_stale_db_connections()
            LOGGER.warning(
                f"Transient failure reaching PostHog's database (attempt {attempt}/{_INTERNAL_DB_MAX_ATTEMPTS}), retrying",
                exc_info=e,
            )
            time.sleep(2**attempt)


def with_internal_db_retries(fn: Callable[P, T]) -> Callable[P, T]:
    """Decorator form of `retry_internal_db_operation`, for an activity whose whole body is
    idempotent work against PostHog's own database. Stack it under `@activity.defn`:

        @activity.defn
        @with_internal_db_retries
        def my_activity(inputs: MyInputs) -> None: ...

    An activity that also does expensive work of its own, such as an S3 listing or an extraction,
    wraps its individual queries with `retry_internal_db_operation` instead, so a blip on a late
    write does not repeat the work before it.
    """

    @wraps(fn)
    def inner(*args: P.args, **kwargs: P.kwargs) -> T:
        return retry_internal_db_operation(lambda: fn(*args, **kwargs))

    return inner


# 10 mins buffer to avoid deleting files Clickhouse may be reading
S3_DELETE_TIME_BUFFER = 600

# A zombie compaction+vacuum pass (a heartbeat-timed-out activity attempt still running) can keep
# deleting source files for as long as its own rewrite takes - documented up to ~45s for a
# fragmented table in core/delta/maintenance.py, before vacuum even starts - which can outlive a
# single retry. Bound the retries with backoff instead, mirroring _purge_s3_prefix's approach to
# the same class of race. 6 attempts gives ~62s of cumulative backoff (2+4+8+16+32s), comfortably
# past that documented worst case; 4 attempts (~14s) wasn't.
_COPY_FILES_MAX_ATTEMPTS = 6

# A recursive delete is idempotent (a folder already gone is the outcome it wanted), so retrying the
# whole delete after a throttling response is as safe as retrying one call. 4 attempts gives ~14s of
# cumulative backoff (2+4+8s), the same budget `_purge_s3_prefix` uses against the same condition.
_DELETE_FOLDER_MAX_ATTEMPTS = 4


def is_posthog_team(team_id: int) -> bool:
    DEBUG: bool = get_from_env("DEBUG", False, type_cast=str_to_bool)
    if DEBUG:
        return True

    region = get_from_env("CLOUD_DEPLOYMENT", optional=True)
    return (region == "EU" and team_id == 1) or (region == "US" and team_id == 2)


async def prepare_s3_files_for_querying(
    folder_path: str,
    table_name: str,
    file_uris: list[str],
    use_timestamped_folders: bool = True,
    existing_queryable_folder: Optional[str] = None,
    preserve_table_name_casing: Optional[bool] = False,
    delete_existing: bool = True,
    logger: Optional[FilteringBoundLogger] = None,
    refresh_file_uris: Optional[Callable[[], Awaitable[list[str]]]] = None,
) -> str:
    """Async version that uses s3fs native async methods for concurrent file operations."""

    async def _log(msg: str, level: Optional[Literal["debug", "error"]] = "debug") -> None:
        if logger:
            if level == "debug":
                await logger.adebug(msg)
            elif level == "error":
                await logger.aerror(msg)

    await _log(
        f"Preparing S3 files for querying for table {table_name} in folder {folder_path}. "
        f"delete_existing={delete_existing}. use_timestamped_folders={use_timestamped_folders}."
    )

    async with aget_s3_client() as s3:
        s3.invalidate_cache()

        normalized_table_name = NamingConvention.normalize_identifier(table_name)

        s3_folder_for_job = f"{settings.BUCKET_URL}/{folder_path}"

        s3_folder_for_schema = (
            f"{s3_folder_for_job}/{table_name}"
            if preserve_table_name_casing is True
            else f"{s3_folder_for_job}/{normalized_table_name}"
        )

        s3_folder_for_querying = f"{normalized_table_name}__query"
        s3_path_for_querying = f"{s3_folder_for_job}/{s3_folder_for_querying}"
        if use_timestamped_folders:
            # Seconds first (the age-based GC below parses them), then a unique suffix:
            # two syncs completing within the same second must not share a folder, or the
            # additive copy below merges two parquet generations into one folder and the
            # s3 glob read returns duplicate rows.
            folder_suffix = f"{int(datetime.now().timestamp())}_{uuid4().hex[:8]}"
            s3_path_for_querying = f"{s3_path_for_querying}_{folder_suffix}"
            s3_folder_for_querying = f"{s3_folder_for_querying}_{folder_suffix}"

        files_to_delete: list[str] = []
        if delete_existing:
            if use_timestamped_folders:
                # Match only directories belonging to this specific table.
                # Keys may be bare folder names or full paths, so use (?:^|.+/) to handle both.
                # The uniqueness suffix is optional so folders created before it existed still match.
                query_folder_pattern = re.compile(
                    rf"(?:^|.+/){re.escape(normalized_table_name)}\_\_query\_(\d+)(?:_[0-9a-f]{{8}})?\/?$"
                )

                try:
                    all_files = await s3._ls(s3_folder_for_job, detail=True)
                except FileNotFoundError:
                    # First materialization for this table/model: the job folder has no
                    # prior content in S3 yet, so there's nothing to clean up.
                    all_files = []
                all_file_values = all_files.values() if isinstance(all_files, dict) else all_files
                directories = [f["Key"] for f in all_file_values if f["type"] == "directory"]

                timestamped_query_folders: list[tuple[str, int]] = []
                for directory in directories:
                    match = query_folder_pattern.match(directory)
                    if match:
                        timestamped_query_folders.append((directory, int(match.group(1))))

                timestamped_query_folders.sort(key=lambda x: x[1])
                total_dirs = len(timestamped_query_folders)
                await _log(
                    f"Found {len(directories)} existing directories; "
                    f"{total_dirs} match query folders for table {normalized_table_name}"
                )

                for index, directory in enumerate(timestamped_query_folders):
                    directory_path, directory_timestamp = directory
                    directory_name = directory_path.rstrip("/").split("/")[-1]
                    if existing_queryable_folder:
                        if existing_queryable_folder == directory_name:
                            await _log(f"Skipping deletion of existing querying folder: {directory_path}")
                            continue
                    else:
                        if index == total_dirs - 1:
                            await _log(f"Skipping deletion of most recent query folder: {directory_path}")
                            continue

                    try:
                        if (datetime.now().timestamp() - directory_timestamp) >= S3_DELETE_TIME_BUFFER:
                            files_to_delete.append(directory_path)

                        old_query_folder = f"{s3_folder_for_job}/{normalized_table_name}__query"
                        if await s3._exists(old_query_folder):
                            files_to_delete.append(old_query_folder)
                    except Exception as e:
                        await _log(f"Error while checking old query folders: {e}", level="error")
                        capture_exception(e)
            else:
                if await s3._exists(s3_path_for_querying):
                    files_to_delete.append(s3_path_for_querying)

        # Copy files concurrently with limited concurrency to avoid overwhelming S3
        await _log(f"Copying {len(file_uris)} files to {s3_path_for_querying}")

        semaphore = asyncio.Semaphore(50)

        async def copy_file(file: str) -> None:
            async with semaphore:
                file_name = file.replace(f"{s3_folder_for_schema}/", "")
                # _cp_file() copies a single known source to a known destination key directly.
                # The generic _copy() also globs the source and probes whether the destination
                # is a directory, each requiring its own S3 ListObjectsV2 call — with hundreds of
                # files copied concurrently, that multiplies into enough LIST traffic to trigger
                # S3's SlowDown rate limiting on the destination prefix.
                await s3._cp_file(file, f"{s3_path_for_querying}/{file_name}")

        import deltalake.exceptions  # noqa: PLC0415 — keeps the heavy deltalake dep off this module's top-level import path

        from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (  # noqa: PLC0415 — keeps the heavy deltalake dep off this module's top-level import path
            is_transient_object_store_error,
        )
        from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (  # noqa: PLC0415 — keeps the heavy deltalake dep off this module's top-level import path
            is_object_store_permission_denied,
        )

        attempt = 0
        while True:
            attempt += 1
            try:
                await asyncio.gather(*[copy_file(file) for file in file_uris])
                break
            except FileNotFoundError as e:
                if refresh_file_uris is None or attempt >= _COPY_FILES_MAX_ATTEMPTS:
                    raise
                # A concurrent compact/vacuum pass on the same Delta table (e.g. a zombie attempt
                # from a heartbeat timeout still running) can physically delete a source file
                # between our listing and this copy. Re-listing picks up wherever that pass left
                # the table; back off first so a still-running pass has time to finish before we
                # retry against it again.
                await _log(
                    f"Source file vanished mid-copy (attempt {attempt}/{_COPY_FILES_MAX_ATTEMPTS}), "
                    f"retrying with a fresh file listing: {e}",
                    level="error",
                )
                await asyncio.sleep(2**attempt)
                try:
                    file_uris = await refresh_file_uris()
                except deltalake.exceptions.TableNotFoundError as refresh_error:
                    # Re-listing reopens the same table mid-race, and can lose it the same way the
                    # copy above did: delta-rs raises this (not FileNotFoundError/OSError) when the
                    # rewrite in progress has left the log segment with zero readable commits for the
                    # moment before its own commit lands. Keep the stale listing so the next attempt's
                    # copy fails the same way and this loop retries the refresh again, instead of the
                    # delta-kernel error escaping uncaught on the first unlucky refresh.
                    await _log(
                        f"Refreshing file listing hit the same table race (attempt "
                        f"{attempt}/{_COPY_FILES_MAX_ATTEMPTS}), retrying: {refresh_error}",
                        level="error",
                    )
            except OSError as e:
                if is_object_store_permission_denied(e):
                    # An explicit AccessDenied/lacked-privileges response is never a race - every
                    # retry would repeat the same refused call, so fail on the first attempt.
                    raise S3OperationError("copy this table's files into its query folder", e)
                # s3fs wraps a CopyObject/PutObject 5xx (e.g. S3's InternalError, already retried to
                # exhaustion at the boto layer) as a plain OSError. That's a blip on S3's side, not a
                # bug here - retry the whole (idempotent) copy batch with backoff before giving up.
                # A bare PermissionError is included too: AWS omits the error code from a HeadObject
                # response body, so s3fs's _cp_file (which HEADs the destination) raises the same
                # PermissionError("Forbidden") for a brief credential-resolution race as it does for a
                # genuine denial (is_object_store_permission_denied only catches the latter, via an
                # explicit code). _purge_s3_prefix retries this same ambiguous case for the same
                # reason - see _is_retryable_purge_error.
                if attempt >= _COPY_FILES_MAX_ATTEMPTS or not (
                    is_transient_object_store_error(e) or _is_s3_throttling_error(e) or isinstance(e, PermissionError)
                ):
                    # Either the failure needs a human (denied permissions, a storage backend with no
                    # free space) or the retries ran out. Both leave the raw s3fs message, so re-raise
                    # as the typed error that names the operation without the bucket and key.
                    raise S3OperationError("copy this table's files into its query folder", e)
                await _log(
                    f"Transient S3 error while copying files (attempt {attempt}/{_COPY_FILES_MAX_ATTEMPTS}), "
                    f"retrying: {e}",
                    level="error",
                )
                await asyncio.sleep(2**attempt)

        # Delete existing files after copying new ones
        if delete_existing and files_to_delete:
            await _log(f"Deleting {len(files_to_delete)} old query folders")

            async def delete_folder(file: str) -> None:
                async with semaphore:
                    delete_attempt = 0
                    while True:
                        delete_attempt += 1
                        try:
                            await s3._rm(file, recursive=True)
                            return
                        except FileNotFoundError:
                            # The folder is already gone: another sync's cleanup pass took it, or an
                            # earlier attempt of this one deleted it and lost the response. That is
                            # the outcome this delete wanted, so there is nothing to report.
                            await _log(f"Old query folder was already deleted: {file}")
                            return
                        except Exception as e:
                            if _is_s3_throttling_error(e) and delete_attempt < _DELETE_FOLDER_MAX_ATTEMPTS:
                                await _log(
                                    f"S3 throttled the delete of old query folder {file} (attempt "
                                    f"{delete_attempt}/{_DELETE_FOLDER_MAX_ATTEMPTS}), retrying: {e}",
                                    level="error",
                                )
                                await asyncio.sleep(2**delete_attempt)
                                continue

                            await _log(f"Error while deleting old query folder {file}: {e}", level="error")
                            if not (_is_transient_s3_connection_error(e) or is_transient_object_store_error(e)):
                                capture_exception(S3OperationError("delete an old query folder for this table", e))
                            # Cleanup stays best effort: the folder is timestamped, so the age-based
                            # GC above picks it up on a later sync. Failing the sync over it would
                            # throw away a load that has already landed.
                            return

            await asyncio.gather(*[delete_folder(file) for file in files_to_delete])

        await _log(f"Returning S3 folder for querying: {s3_folder_for_querying}")

    return s3_folder_for_querying
