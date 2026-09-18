import asyncio
from typing import Any

from django.conf import settings

import deltalake as deltalake
import deltalake.exceptions
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool

from products.data_warehouse.backend.facade.api import aget_s3_client, delta_proxy_storage_options, ensure_bucket_exists
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    conditional_lru_cache_async,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    TransientObjectStoreError,
    is_transient_delta_maintenance_error,
    is_transient_object_store_error,
)

# _purge_s3_prefix is idempotent (every step is existence-gated), so retrying it whole after a brief
# backoff is as safe as retrying a single failed call, and simpler.
_PURGE_S3_PREFIX_MAX_ATTEMPTS = 4


def _is_retryable_purge_error(error: OSError) -> bool:
    """True for an error worth retrying `_purge_s3_prefix` on.

    Covers the known-transient object-store blips (see is_transient_object_store_error) plus a bare
    `PermissionError`: s3fs translates every S3 auth-failure response code (AccessDenied,
    ExpiredToken, InvalidAccessKeyId, ...) into this one exception type, and a HeadObject 403 never
    carries the underlying code in its body (AWS omits it for HEAD requests), so a transient
    credential-resolution race can't be told apart from a genuine permission problem by message here.
    `_purge_s3_prefix` always runs against a freshly created client (aget_s3_client(fresh_instance=True)),
    which re-resolves credentials on every call — the same IMDS/STS race already covered for
    NoCredentialsError above, just surfacing as an explicit S3-side denial instead of a local
    resolution failure. Retrying the same bounded budget lets that race self-heal; a persistent
    misconfiguration still raises once the budget is exhausted, since this only defers the error.
    """
    return is_transient_object_store_error(error) or isinstance(error, PermissionError)


async def _purge_s3_prefix(s3: Any, uri: str) -> None:
    """Delete every object under `uri`, retrying on transient S3 SlowDown throttling.

    Bulk-listing and bulk-deleting a table's worth of objects can trip S3's `SlowDown` response
    under enough request volume; retry the whole (idempotent) purge with backoff before giving up.
    """
    attempt = 0
    while True:
        try:
            await _purge_s3_prefix_once(s3, uri)
            return
        except OSError as e:
            attempt += 1
            if attempt >= _PURGE_S3_PREFIX_MAX_ATTEMPTS or not _is_retryable_purge_error(e):
                raise
            await asyncio.sleep(2**attempt)


async def _purge_s3_prefix_once(s3: Any, uri: str) -> None:
    """Delete every object under `uri`, resilient to S3 recursive-delete gaps.

    A lone `_rm(uri, recursive=True)` can leave objects behind on S3-compatible stores (directory
    markers, and — mid-write — partial `_delta_log` files). Strays are corrupting: a later
    `write_deltalake` append onto a half-cleared temp then sees a malformed table ("No table metadata
    or protocol found in delta log"), and a swap copy that lands on top of undeleted live files leaves
    a merged `_delta_log` whose row count is wrong ("swap verification failed: live > expected").
    Enumerate and delete explicitly first, then a best-effort recursive sweep.

    The dircache is dropped first: delta-rs writes through its own Rust object store, so s3fs's
    listing cache never learns about those files — a cached listing would leave exactly them behind.
    """
    s3.invalidate_cache()
    if not await s3._exists(uri):
        return
    files = await s3._find(uri)
    if files:
        await s3._rm([f"s3://{f.lstrip('/')}" for f in files])
    if await s3._exists(uri):
        await s3._rm(uri, recursive=True)


def build_delta_table_uri(folder_path: str, resource_name: str) -> str:
    """Canonical S3 URI of a schema's Delta table.

    The writer (`DeltaTableRef`) and readers (e.g. the fan-out warehouse parent reader)
    must agree byte-for-byte on where a table lives; both derive it here.
    """
    normalized_name = NamingConvention.normalize_identifier(resource_name)
    return f"{settings.BUCKET_URL}/{folder_path}/{normalized_name}"


def delta_storage_options() -> dict[str, str]:
    """delta-rs storage options for the data-warehouse bucket, independent of any import job — so a
    read path (e.g. the person-property backfill) can open a Delta table without constructing a full
    ``DeltaTableRef`` (which carries caching, first-sync mutation, and corruption-repair)."""
    if settings.USE_LOCAL_SETUP:
        if (
            not settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY
            or not settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET
            or not settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION
        ):
            raise KeyError(
                "Missing env vars for data warehouse. Required vars: DATAWAREHOUSE_LOCAL_ACCESS_KEY, DATAWAREHOUSE_LOCAL_ACCESS_SECRET, DATAWAREHOUSE_LOCAL_BUCKET_REGION"
            )

        ensure_bucket_exists(
            settings.BUCKET_URL,
            settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
            settings.OBJECT_STORAGE_ENDPOINT,
        )

        options = {
            "aws_access_key_id": settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            "aws_secret_access_key": settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region_name": settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION,
            "AWS_DEFAULT_REGION": settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION,
            "AWS_ALLOW_HTTP": "true",
        }
    else:
        options = dict(delta_proxy_storage_options())

    # Conditional puts make a clashing concurrent commit fail loudly instead of
    # clobbering _delta_log; set explicitly so a library default change can't undo it.
    options["conditional_put"] = "etag"
    if settings.DATA_WAREHOUSE_DELTA_S3_ALLOW_UNSAFE_RENAME:
        options["AWS_S3_ALLOW_UNSAFE_RENAME"] = "true"
    return options


class DeltaTableRef:
    """Handle to one schema's Delta table: uri/credentials, the cached open (with corrupt-table
    auto-heal), corruption detection, reset, file listing, and the first-sync flag.

    This is the single stateful object threaded through a sync run. The operations over the table
    are stateless wrappers constructed at their call sites: `DeltaWriter`, `Scd2DeltaWriter`, and
    `DeltaMaintenance`.
    """

    _resource_name: str
    _job: ExternalDataJob
    _logger: FilteringBoundLogger
    _is_first_sync: bool

    def __init__(
        self, resource_name: str, job: ExternalDataJob, logger: FilteringBoundLogger, is_first_sync: bool = False
    ) -> None:
        self._resource_name = resource_name
        self._job = job
        self._logger = logger
        self._is_first_sync = is_first_sync

    @property
    def is_first_sync(self) -> bool:
        return self._is_first_sync

    @property
    def job(self) -> ExternalDataJob:
        return self._job

    @property
    def resource_name(self) -> str:
        return self._resource_name

    @property
    def logger(self) -> FilteringBoundLogger:
        return self._logger

    def _get_credentials(self):
        return delta_storage_options()

    async def _get_delta_table_uri(self) -> str:
        folder_path = await database_sync_to_async_pool(self._job.folder_path)()
        return build_delta_table_uri(folder_path, self._resource_name)

    async def get_table_uri(self) -> str:
        """Public accessor for the live Delta table S3 URI (used by the in-place repartitioner)."""
        return await self._get_delta_table_uri()

    def get_storage_options(self) -> dict[str, str]:
        """Public accessor for the delta-rs storage options (used by the in-place repartitioner)."""
        return self._get_credentials()

    async def _capture_unless_transient(self, e: Exception) -> None:
        """capture_exception unless `e` is a known-transient object-store blip (see
        is_transient_object_store_error) or a concurrent-purge race on `_delta_log` (see
        is_transient_delta_maintenance_error — the open below can lose that same race a maintenance
        pass can) — those recover on retry and aren't a defect, so reporting them to error tracking
        is just noise. A transient blip is re-raised as TransientObjectStoreError instead of letting
        the original propagate: the activity interceptor reports any uncaught activity exception
        unless it's a NonReportableError, so a bare re-raise here would still mint a fresh issue at
        that boundary. Never suppresses the re-raise itself, so Temporal's activity retry policy is
        unaffected either way.
        """
        if is_transient_object_store_error(e) or is_transient_delta_maintenance_error(e):
            await self._logger.awarning(f"get_delta_table: transient object-store error, not reporting: {e}")
            raise TransientObjectStoreError(str(e)) from e
        capture_exception(e)

    @conditional_lru_cache_async(maxsize=1, condition=lambda result: result is not None)
    async def get_delta_table(self) -> deltalake.DeltaTable | None:
        delta_uri = await self._get_delta_table_uri()
        storage_options = self._get_credentials()

        try:
            is_delta = await asyncio.to_thread(
                deltalake.DeltaTable.is_deltatable, table_uri=delta_uri, storage_options=storage_options
            )
        except Exception as e:
            # Mirrors the DeltaTable() open below: capture before propagating. Callers range from
            # best-effort maintenance to the main write path, so this can't safely swallow the
            # error and report "no table" here — that would trip should_overwrite_table for a
            # table that actually exists, risking data loss.
            await self._capture_unless_transient(e)
            raise

        if is_delta:
            try:
                return await asyncio.to_thread(
                    deltalake.DeltaTable, table_uri=delta_uri, storage_options=storage_options
                )
            except Exception as e:
                await self._capture_unless_transient(e)
                error_text = "".join(str(arg) for arg in e.args)
                # Unrecoverable tables (bugged decimals, or an orphaned _delta_log missing its
                # metadata action or containing no commit files at all, which can't happen on a
                # healthy table since `is_deltatable` above already confirmed the log directory
                # exists): wipe so the sync starts fresh. "No files in log segment" is delta-rs's
                # own kernel raising `DeltaTableError::NotATable` because the log directory has
                # zero usable commit files, e.g. a stray marker left by an interrupted purge/write.
                if (
                    "parse decimal overflow" in error_text
                    or "No table metadata or protocol found" in error_text
                    or "No files in log segment" in error_text
                ):
                    await self._logger.aerror(
                        f"get_delta_table: deleting unrecoverable delta table for a fresh sync: {error_text}"
                    )
                    # A bare recursive `_rm` can leave `_delta_log` strays behind on S3-compatible
                    # stores (see `_purge_s3_prefix_once`), which would recreate this exact
                    # "No table metadata or protocol found" corruption on the very next sync.
                    async with aget_s3_client(fresh_instance=True) as s3:
                        try:
                            await _purge_s3_prefix(s3, delta_uri)
                        except FileNotFoundError:
                            pass
                else:
                    raise

        self._is_first_sync = True

        return None

    async def is_table_corrupted(self) -> bool:
        """True when the Delta log exists but the table can't be opened (DeltaError / FileNotFoundError).

        The signature of a `_delta_log` left inconsistent by an interrupted repartition swap or an
        OOM-crashed merge — after which every sync fails to open the table and loops. Non-destructive:
        only attempts an open (bypassing the get_delta_table cache). A table that simply doesn't exist is
        not corrupt; an unknown open error is not classified as corrupt, so a transient failure never
        triggers a destructive revive. A recognized transient blip (see is_transient_object_store_error,
        is_transient_delta_maintenance_error) is excluded the same way — otherwise a concurrent purge
        racing this open would misread as corruption and trigger a needless destructive revive.
        """
        delta_uri = await self._get_delta_table_uri()
        storage_options = self._get_credentials()

        is_delta = await asyncio.to_thread(
            deltalake.DeltaTable.is_deltatable, table_uri=delta_uri, storage_options=storage_options
        )
        if not is_delta:
            return False

        try:
            await asyncio.to_thread(deltalake.DeltaTable, table_uri=delta_uri, storage_options=storage_options)
            return False
        except (deltalake.exceptions.DeltaError, FileNotFoundError) as e:
            if is_transient_object_store_error(e) or is_transient_delta_maintenance_error(e):
                return False
            return True
        except Exception:
            return False

    async def reset_table(self):
        delta_uri = await self._get_delta_table_uri()

        # Explicit purge on a fresh client: a stale dircache or an incomplete recursive delete can
        # leave `_delta_log` strays behind, and the rebuild then commits version 0 into a log that
        # still holds old commits — recreating exactly the corruption a reset is meant to clear.
        async with aget_s3_client(fresh_instance=True) as s3:
            try:
                await _purge_s3_prefix(s3, delta_uri)
            except FileNotFoundError:
                pass

        self.get_delta_table.cache_clear()

        await self._logger.adebug("reset_table: _is_first_sync=True")
        self._is_first_sync = True

    async def get_file_uris(self) -> list[str]:
        delta_table = await self.get_delta_table()
        if delta_table is None:
            return []

        return await asyncio.to_thread(delta_table.file_uris)
