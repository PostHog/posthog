import asyncio
from typing import Any

from django.conf import settings

import pyarrow as pa
import deltalake as deltalake
import pyarrow.compute as pc
import deltalake.exceptions
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool

from products.data_warehouse.backend.facade.api import aget_s3_client, delta_proxy_storage_options, ensure_bucket_exists
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.deltalite_handles import (
    get_handle_cache,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    TransientObjectStoreError,
    is_transient_delta_maintenance_error,
    is_transient_object_store_error,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    OBJECT_STORE_PERMISSION_DENIED_MESSAGE,
    ObjectStorePermissionDeniedError,
    is_object_store_permission_denied,
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

    The `PermissionError` clause only ever sees a bodyless 403, because `_purge_s3_prefix` classifies
    a response that does carry an explicit `AccessDenied` code before reaching here (see
    is_object_store_permission_denied) and raises on it instead of retrying.
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
            if is_object_store_permission_denied(e):
                # S3 only returns an explicit AccessDenied code when a policy refuses the call, so
                # every remaining attempt would make the same refused DeleteObjects calls and only
                # delay the failure. Raise a typed error on the first one, and keep the object key
                # it names out of the message the customer reads.
                raise ObjectStorePermissionDeniedError(OBJECT_STORE_PERMISSION_DENIED_MESSAGE) from e
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


def live_row_count(delta_table: deltalake.DeltaTable) -> int | None:
    """Rows in the table's live files, summed from the `numRecords` statistic of each Add action.

    The query folder holds a copy of exactly the live files, so this sum is the number a `count()`
    over that folder returns, without a read of any data file. Deletion vectors do not change this,
    because the copied files also keep every physical row.

    None when a live file has no statistic or the log cannot give the statistics. The caller then
    counts the files instead.
    """
    try:
        add_actions = pa.table(delta_table.get_add_actions(flatten=False))
    except Exception:
        # The stats of a large table can overflow Arrow's 32-bit string offsets (see
        # repartition.measure_partition_bytes), and the fallback count gives the same number.
        return None
    if "num_records" not in add_actions.column_names:
        return None
    num_records = add_actions.column("num_records")
    if num_records.null_count:
        return None
    return int(pc.sum(num_records).as_py() or 0)


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
    _cached_table: deltalake.DeltaTable | None
    #: True while a deltalite commit has advanced the log past the cached handle's snapshot.
    _cached_table_stale: bool
    #: The newest version deltalite reported committing through this ref, if any.
    _deltalite_version: int | None
    _table_uri: str | None
    #: A hint that the next open will find no table. It only selects which request goes first.
    _expect_missing: bool
    #: True from an open that found no table until this ref creates, resets or invalidates it.
    _known_missing: bool

    def __init__(
        self,
        resource_name: str,
        job: ExternalDataJob,
        logger: FilteringBoundLogger,
        is_first_sync: bool = False,
        *,
        expect_missing: bool | None = None,
    ) -> None:
        self._resource_name = resource_name
        self._job = job
        self._logger = logger
        self._is_first_sync = is_first_sync
        self._cached_table = None
        self._cached_table_stale = False
        self._deltalite_version = None
        self._table_uri = None
        self._expect_missing = is_first_sync if expect_missing is None else expect_missing
        self._known_missing = False

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
        self._table_uri = build_delta_table_uri(folder_path, self._resource_name)
        return self._table_uri

    async def get_table_uri(self) -> str:
        """Public accessor for the live Delta table S3 URI (used by the in-place repartitioner)."""
        uri = await self._get_delta_table_uri()
        self._table_uri = uri
        return uri

    def get_storage_options(self) -> dict[str, str]:
        """Public accessor for the delta-rs storage options (used by the in-place repartitioner)."""
        return self._get_credentials()

    async def _capture_unless_transient(self, e: Exception) -> None:
        """capture_exception unless `e` is already classified as something other than a defect.

        A known-transient object-store blip (see is_transient_object_store_error) or a
        concurrent-purge race on `_delta_log` (see is_transient_delta_maintenance_error, because the
        open below can lose the same race a maintenance pass can) recovers on retry, so reporting it
        to error tracking is just noise. Both are re-raised as TransientObjectStoreError instead of
        letting the original propagate, because the activity interceptor reports any uncaught
        activity exception unless it is a NonReportableError, which TransientObjectStoreError is, so
        a bare re-raise here would still mint a fresh issue at that boundary.

        An object-store refusal (see is_object_store_permission_denied) is re-raised as
        ObjectStorePermissionDeniedError, which is not a NonReportableError: a refusal on our own
        bucket needs a human, so it is still reported, once, under a message that names no object key.

        Never suppresses the re-raise itself, so Temporal's activity retry policy is unaffected
        whichever branch runs.
        """
        if is_object_store_permission_denied(e):
            # The bucket refused the read, which is a policy condition on our own storage rather
            # than a defect in this code or a corrupt table. Raising the typed error instead of
            # capturing here leaves one report at the activity boundary rather than two, and its
            # message carries no `_delta_log` key, so the customer's error text stays free of the
            # object key and error tracking gets one issue instead of one per table.
            #
            # Classified before the transient check, because delta-rs prefixes many object-store
            # errors with "Generic S3 error", which that check treats as transient on its own. A
            # refusal that arrives under that prefix is still definitive, and retrying it would
            # hide it behind Temporal's retry policy until the activity gave up.
            await self._logger.aerror(f"get_delta_table: the object store denied the read ({type(e).__name__})")
            raise ObjectStorePermissionDeniedError(OBJECT_STORE_PERMISSION_DENIED_MESSAGE) from e
        if is_transient_object_store_error(e) or is_transient_delta_maintenance_error(e):
            await self._logger.awarning(f"get_delta_table: transient object-store error, not reporting: {e}")
            raise TransientObjectStoreError(str(e)) from e
        capture_exception(e)

    async def get_delta_table(
        self, *, allow_stale: bool = False, allow_known_missing: bool = False
    ) -> deltalake.DeltaTable | None:
        """Open the table once and hand back the same handle for the rest of this ref's life.

        The cache is per instance on purpose. A process-wide slot lets any other table in flight on
        the same worker evict this one's handle, and every re-open is a full Delta-log replay against
        object storage. Writes through the handle keep it current, so it stays valid until this ref's
        own `invalidate_cached_table` (reset, repartition swap) says otherwise.

        A missing table is looked for again on each call, so a table that another writer created
        after the first probe is found. `allow_known_missing` skips that second look. It is only for
        a caller whose result does not depend on the answer: a write that overwrites the table,
        which creates the table itself when the answer is None (see `adopt_created_table`).

        A deltalite write commits past this handle (see `note_deltalite_commit`), after which the
        cached snapshot is behind the log by that commit: same table id, same columns, same
        partition layout, but an older version and file list. The handle catches up on the next call
        with one incremental log read. `allow_stale` skips that read for a caller whose reads a
        deltalite commit cannot change; anything that reads the version, the file list or the
        per-file statistics must leave it False.
        """
        if self._cached_table is not None:
            if self._cached_table_stale and not allow_stale:
                await self._refresh_cached_table(self._cached_table)
            return self._cached_table
        if allow_known_missing and self._known_missing:
            return None
        table = await self._open_delta_table()
        self._cached_table = table
        self._cached_table_stale = False
        self._known_missing = table is None
        return table

    def adopt_created_table(self, table: deltalake.DeltaTable) -> None:
        """Keep the handle of a table that the caller just created at this ref's URI.

        A new table has no log to replay, so the handle from the create call is the same snapshot
        that a new open gives. The writes that follow go through it and keep it current.
        """
        self._cached_table = table
        self._cached_table_stale = False
        self._known_missing = False
        self._expect_missing = False

    async def _refresh_cached_table(self, table: deltalake.DeltaTable) -> None:
        try:
            await asyncio.to_thread(table.update_incremental)
        except Exception as e:
            # The handle stays marked, so the next reader tries again instead of reading a snapshot
            # that is known to be behind.
            await self._capture_unless_transient(e)
            raise
        self._cached_table_stale = False

    def note_deltalite_commit(self, version: int | None) -> None:
        """Record that deltalite committed `version` to this table outside the cached handle.

        The cached delta-rs handle is marked behind the log until the next `get_delta_table` call
        refreshes it. The version is kept so `latest_known_version` can report it in the meantime.
        """
        self._cached_table_stale = True
        if version is not None and (self._deltalite_version is None or version > self._deltalite_version):
            self._deltalite_version = version

    def latest_known_version(self, delta_table: deltalake.DeltaTable) -> int:
        """The newest version this ref knows the table reached: the handle's, or a later deltalite commit."""
        version = delta_table.version()
        if self._deltalite_version is not None and self._deltalite_version > version:
            return self._deltalite_version
        return version

    def invalidate_cached_table(self) -> None:
        """Drop the cached handle so the next `get_delta_table` re-reads the live Delta log.

        The process-wide deltalite handle for this table goes with it: a reset or a repartition swap
        has replaced the table under the same URI, and that handle's snapshot describes the old one.
        """
        self._forget_cached_table()
        if self._table_uri is not None:
            get_handle_cache().invalidate(self._table_uri)

    def pop_cached_table(self) -> deltalake.DeltaTable | None:
        """Release the cached handle without opening the table, for end-of-run memory cleanup."""
        table = self._cached_table
        self._forget_cached_table()
        return table

    def _forget_cached_table(self) -> None:
        # A version noted for the old handle describes a table incarnation this ref is done with.
        self._cached_table = None
        self._cached_table_stale = False
        self._deltalite_version = None
        self._known_missing = False

    async def _open_directly(self, delta_uri: str, storage_options: dict[str, str]) -> deltalake.DeltaTable | None:
        """Open the table with no existence check first, or None when that open fails.

        A table that opens always has a commit or a checkpoint in its log, which is what
        `is_deltatable` looks for, so a successful open needs no second answer. A failed open says
        nothing here: the caller runs the existence check and the open again, in that order, and
        classifies the error from that second attempt. Thus a missing table, a prefix that is not a
        table, a damaged log and a refused request all get the same handling as before.

        Skipped when the table is expected to be missing, because the existence check alone is then
        the cheaper first request.
        """
        if self._expect_missing:
            return None
        try:
            return await asyncio.to_thread(deltalake.DeltaTable, table_uri=delta_uri, storage_options=storage_options)
        except Exception:
            return None

    async def _open_delta_table(self) -> deltalake.DeltaTable | None:
        delta_uri = await self._get_delta_table_uri()
        storage_options = self._get_credentials()

        table = await self._open_directly(delta_uri, storage_options)
        if table is not None:
            return table

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
        self._expect_missing = True

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

        if await self._open_directly(delta_uri, storage_options) is not None:
            return False

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

        self.invalidate_cached_table()

        await self._logger.adebug("reset_table: _is_first_sync=True")
        self._is_first_sync = True
        self._expect_missing = True

    async def get_file_uris(self) -> list[str]:
        delta_table = await self.get_delta_table()
        if delta_table is None:
            return []

        return await asyncio.to_thread(delta_table.file_uris)

    async def get_live_row_count(self) -> int | None:
        """The table's row count from the Delta log, or None when the log cannot give it (see
        `live_row_count`)."""
        delta_table = await self.get_delta_table()
        if delta_table is None:
            return None

        row_count = await asyncio.to_thread(live_row_count, delta_table)
        if row_count is None:
            await self._logger.adebug("The Delta log has no complete row count, counting the published files")
        return row_count
