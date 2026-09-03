import re
import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal, Optional
from uuid import uuid4

from django.conf import settings

import botocore.exceptions
from structlog.types import FilteringBoundLogger

from posthog.exceptions import capture_exception
from posthog.settings.utils import get_from_env
from posthog.temporal.common.errors import NonReportableError
from posthog.utils import str_to_bool

from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention

# A best-effort delete of old query folders can hit a transient S3 connectivity blip
# (connect/read timeout, dropped connection). The folder is timestamped and simply gets
# picked up by the age-based GC on a later sync, so these aren't worth an error-tracking
# issue - unlike a real failure (permissions, missing bucket), which still gets captured.
_TRANSIENT_S3_CONNECTION_EXCEPTIONS = (
    botocore.exceptions.ConnectionError,  # covers ConnectTimeoutError, EndpointConnectionError
    botocore.exceptions.ReadTimeoutError,
    botocore.exceptions.ConnectionClosedError,
)


def _is_transient_s3_connection_error(error: BaseException) -> bool:
    return isinstance(error, _TRANSIENT_S3_CONNECTION_EXCEPTIONS)


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


# 10 mins buffer to avoid deleting files Clickhouse may be reading
S3_DELETE_TIME_BUFFER = 600

# A zombie compaction+vacuum pass (a heartbeat-timed-out activity attempt still running) can keep
# deleting source files for as long as its own rewrite takes - documented up to ~45s for a
# fragmented table in core/delta/maintenance.py, before vacuum even starts - which can outlive a
# single retry. Bound the retries with backoff instead, mirroring _purge_s3_prefix's approach to
# the same class of race. 6 attempts gives ~62s of cumulative backoff (2+4+8+16+32s), comfortably
# past that documented worst case; 4 attempts (~14s) wasn't.
_COPY_FILES_MAX_ATTEMPTS = 6


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

        from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (  # noqa: PLC0415 — keeps the heavy deltalake dep off this module's top-level import path
            is_transient_object_store_error,
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
                file_uris = await refresh_file_uris()
            except OSError as e:
                # s3fs wraps a CopyObject/PutObject 5xx (e.g. S3's InternalError, already retried to
                # exhaustion at the boto layer) as a plain OSError. That's a blip on S3's side, not a
                # bug here - retry the whole (idempotent) copy batch with backoff before giving up.
                if attempt >= _COPY_FILES_MAX_ATTEMPTS or not is_transient_object_store_error(e):
                    raise
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
                    try:
                        await s3._rm(file, recursive=True)
                    except Exception as e:
                        await _log(f"Error while deleting old query folder {file}: {e}", level="error")
                        if not _is_transient_s3_connection_error(e):
                            capture_exception(e)

            await asyncio.gather(*[delete_folder(file) for file in files_to_delete])

        await _log(f"Returning S3 folder for querying: {s3_folder_for_querying}")

    return s3_folder_for_querying
