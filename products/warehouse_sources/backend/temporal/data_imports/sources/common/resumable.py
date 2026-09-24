import json
import hashlib
import functools
import dataclasses
import collections.abc
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Generic

from django.conf import settings

import redis
import orjson
import redis.exceptions as redis_exceptions
from structlog.types import FilteringBoundLogger

from posthog.redis import get_client

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema_resume import (
    ResumeCheckpoint,
    ResumeWindow,
    SchemaResumeStore,
    clear_schema_resume_state,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import ResumableData, SourceInputs

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


class ResumableSourceManager(Generic[ResumableData]):
    _inputs: SourceInputs
    _data_class: type[ResumableData]
    _logger: FilteringBoundLogger
    _namespace: str | None
    _staged: dict[str, str]

    @staticmethod
    def clear_schema_state(*, team_id: int, schema_id: str) -> None:
        clear_schema_resume_state(team_id=team_id, schema_id=schema_id)

    def __init__(
        self,
        inputs: SourceInputs,
        data_class: type[ResumableData],
        namespace: str | None = None,
        staged: dict[str, str] | None = None,
        *,
        resume_across_jobs: bool = False,
        schema_stores: dict[str, SchemaResumeStore] | None = None,
    ) -> None:
        self._inputs = inputs
        self._data_class = data_class
        self._logger = inputs.logger
        self._namespace = namespace
        # Cursors wait here until commit(). Siblings from with_namespace() share the dict, so the
        # one commit the pipeline issues after a write covers every namespace a source touched.
        self._staged = staged if staged is not None else {}
        self._resume_across_jobs = resume_across_jobs
        self._schema_stores = schema_stores if schema_stores is not None else {}

    def with_namespace(self, namespace: str) -> "ResumableSourceManager[ResumableData]":
        """Return a sibling manager whose Redis state is isolated under `namespace`.

        A source that reaches more than one endpoint within a single job — where each
        endpoint stores an incompatible cursor format — uses this to keep their resume
        state in separate slots. Without it a retry that switches endpoints could load a
        cursor the other endpoint wrote and replay it against an API that can't parse it.
        """
        sibling = ResumableSourceManager(
            self._inputs,
            self._data_class,
            namespace=namespace,
            staged=self._staged,
            resume_across_jobs=self._resume_across_jobs,
            schema_stores=self._schema_stores,
        )
        store = self._schema_stores.get(self._key)
        if store is not None and sibling._key not in self._schema_stores:
            sibling_store = store.with_namespace(namespace, job_key=sibling._key)
            self._schema_stores[sibling._key] = sibling_store
            with self._get_redis() as client:
                sibling_store.prepare(client, reset_pipeline=self._inputs.reset_pipeline)
        return sibling

    def prepare_for_schema(
        self,
        schema: "ExternalDataSchema",
        source: "ExternalDataSource",
        *,
        is_durable: collections.abc.Callable[[ResumeCheckpoint], bool],
    ) -> None:
        if not self._resume_across_jobs or not schema.should_use_incremental_field or schema.sync_type is None:
            return
        value = self._inputs.db_incremental_field_last_value
        window = ResumeWindow(
            incremental_field_last_value=schema._serialize_incremental_value(value) if value is not None else None,
            sync_type=schema.sync_type,
            incremental_field=schema.incremental_field,
            incremental_field_type=schema.incremental_field_type,
            source_id=str(source.id),
            api_version=self._inputs.api_version,
            source_config_hash=hashlib.sha256(orjson.dumps(source.job_inputs, option=orjson.OPT_SORT_KEYS)).hexdigest(),
        )
        store = SchemaResumeStore(
            team_id=self._inputs.team_id,
            schema_id=self._inputs.schema_id,
            job_id=self._inputs.job_id,
            job_key=self._key,
            window=window,
            is_durable=is_durable,
            logger=self._logger,
            namespace=self._namespace,
        )
        self._schema_stores[self._key] = store
        with self._get_redis() as client:
            self._write_with_stale_replica_retry(
                client,
                functools.partial(
                    store.prepare,
                    client,
                    reset_pipeline=self._inputs.reset_pipeline or bool(schema.sync_type_config.get("reset_pipeline")),
                ),
            )

    @property
    def pass_high_water_mark(self) -> str | int | float | None:
        store = self._schema_stores.get(self._key)
        return store.high_water_mark if store is not None else None

    def restart_schema_state(self) -> None:
        if not self._schema_stores:
            return
        with self._get_redis() as client:
            for store in self._schema_stores.values():
                self._write_with_stale_replica_retry(client, functools.partial(store.restart, client))

    @contextmanager
    def _get_redis(self):
        if not settings.DATA_WAREHOUSE_REDIS_HOST or not settings.DATA_WAREHOUSE_REDIS_PORT:
            raise Exception(
                "Missing env vars for dwh row tracking: DATA_WAREHOUSE_REDIS_HOST or DATA_WAREHOUSE_REDIS_PORT"
            )

        redis = get_client(f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/")
        redis.ping()

        yield redis

    @property
    def _key(self) -> str:
        base = f"posthog:data_warehouse:resumable_source:{self._inputs.team_id}:{self._inputs.job_id}"
        return f"{base}:{self._namespace}" if self._namespace else base

    def _dump_json(self, data: ResumableData) -> str:
        data_dict = dataclasses.asdict(data)

        try:
            return orjson.dumps(data_dict).decode()
        except TypeError:
            try:
                return json.dumps(data_dict)
            except Exception:
                return str(data_dict)

    def _load_json(self, data: str) -> ResumableData:
        try:
            parsed_data = orjson.loads(data)
        except orjson.JSONDecodeError:
            try:
                parsed_data = json.loads(data)
            except Exception as e:
                raise ValueError(f"Failed to load resumable data: {data}") from e

        # Fields the running code does not know come from state a newer deploy wrote. Dropping
        # them makes a rollback a cache miss; passing them through raises TypeError and fails
        # every resume until the key expires.
        known = {field.name for field in dataclasses.fields(self._data_class)}
        unknown = sorted(set(parsed_data) - known)
        if unknown:
            self._logger.debug(f"Dropping unknown resumable state fields. key={self._key}, fields={unknown}")
        return self._data_class(**{name: value for name, value in parsed_data.items() if name in known})

    def _write_with_stale_replica_retry(self, client: redis.Redis, write: collections.abc.Callable[[], None]) -> None:
        """Run a Redis write, retrying once if the connection now points at a demoted replica.

        `get_client` caches one connection pool for the lifetime of the worker process. A Redis
        failover can promote a different node to primary while this pool still holds a connection
        to the now-demoted node, so every write on it fails with ``ReadOnlyError`` until the pool
        is forced to reconnect. Disconnecting and retrying once means a passing failover costs at
        most one failed write instead of every write for the rest of the worker's life.
        """
        try:
            write()
        except redis_exceptions.ReadOnlyError:
            client.connection_pool.disconnect()
            write()

    def save_state(self, data: ResumableData) -> None:
        """Stage `data` as the cursor to resume from once every row yielded so far is written.

        Nothing reaches Redis until commit(), which the pipeline calls right after a write lands.
        A source with nothing outstanding stages inside committing(), which commits at block end.
        """
        json_data = self._dump_json(data)
        self._logger.debug(f"Staging resumable source state. key={self._key}, data={json_data}")
        self._staged[self._key] = json_data

    def commit(
        self,
        *,
        high_water_mark: str | int | float | None = None,
        job_created_at: datetime | None = None,
        run_uuid: str | None = None,
        batch_index: int | None = None,
    ) -> None:
        """Persist every staged cursor, across namespaces."""
        if not self._staged:
            return
        with self._get_redis() as redis_client:
            for key, json_data in list(self._staged.items()):
                self._logger.debug(f"Saving resumable source state. key={key}, data={json_data}")
                store = self._schema_stores.get(key)
                if (
                    store is not None
                    and job_created_at is not None
                    and run_uuid is not None
                    and batch_index is not None
                ):
                    checkpoint = ResumeCheckpoint(
                        cursor=json_data,
                        high_water_mark=high_water_mark,
                        job_id=self._inputs.job_id,
                        job_created_at=job_created_at,
                        run_uuid=run_uuid,
                        batch_index=batch_index,
                        saved_at=datetime.now(UTC),
                    )
                    self._write_with_stale_replica_retry(
                        redis_client, functools.partial(store.commit, redis_client, checkpoint)
                    )
                else:
                    self._write_with_stale_replica_retry(
                        redis_client,
                        functools.partial(redis_client.set, key, json_data, ex=60 * 60 * 24),  # 24 hours expiration
                    )
                del self._staged[key]

    @contextmanager
    def committing(self) -> collections.abc.Iterator[None]:
        """Commit whatever the block stages, even when the block raises.

        For a bookmark that must persist before any row exists, such as an export or report id the
        source polls before it yields. The pipeline has no write to commit on, so the source does.
        """
        try:
            yield
        finally:
            self.commit()

    def clear_state(self) -> None:
        """Drop any saved resume state so a subsequent attempt starts from scratch.

        Called once a source has walked its data to completion: leaving the final checkpoint in
        place would let a later attempt resume mid-stream instead of restarting cleanly.
        """
        self._staged.pop(self._key, None)
        with self._get_redis() as redis_client:
            self._logger.debug(f"Clearing resumable source state. key={self._key}")
            store = self._schema_stores.get(self._key)
            self._write_with_stale_replica_retry(
                redis_client,
                functools.partial(store.clear, redis_client) if store else lambda: redis_client.delete(self._key),
            )

    def can_resume(self) -> bool:
        with self._get_redis() as redis:
            exists = redis.exists(self._key) == 1
            self._logger.debug(f"Checking resumable source state. key={self._key}, exists={exists}")

            return exists

    def load_state(self) -> ResumableData | None:
        with self._get_redis() as redis:
            data = redis.get(self._key)
            if not data:
                self._logger.debug(f"No resumable source state found. key={self._key}")
                return None

            self._logger.debug(f"Loading resumable source state. key={self._key}, data={data}")
            return self._load_json(data)
