import json
import dataclasses
import collections.abc
from contextlib import contextmanager
from typing import Generic

from django.conf import settings

import redis
import orjson
import redis.exceptions as redis_exceptions
from structlog.types import FilteringBoundLogger

from posthog.redis import get_client

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    ResumableData,
    SourceInputs,
    SourceResponse,
)

# Longer than the longest sync interval (30 days) plus the retries of the run that stopped. A walk
# too long for one run's retry budget then continues in the next scheduled run instead of starting
# again from the first row.
RESUME_STATE_TTL_SECONDS = 60 * 60 * 24 * 35

# The hash field that records which job wrote the state. Namespaces use the other fields.
_JOB_ID_FIELD = "__job_id__"


class ResumableSourceManager(Generic[ResumableData]):
    _inputs: SourceInputs
    _data_class: type[ResumableData]
    _logger: FilteringBoundLogger
    _namespace: str | None
    _staged: dict[str, str]

    def __init__(
        self,
        inputs: SourceInputs,
        data_class: type[ResumableData],
        namespace: str | None = None,
        staged: dict[str, str] | None = None,
    ):
        self._inputs = inputs
        self._data_class = data_class
        self._logger = inputs.logger
        self._namespace = namespace
        # Cursors wait here until commit(), keyed by hash field. Siblings from with_namespace() share
        # the dict, so the one commit the pipeline issues after a write covers every namespace a
        # source touched.
        self._staged = staged if staged is not None else {}

    def with_namespace(self, namespace: str) -> "ResumableSourceManager[ResumableData]":
        """Return a sibling manager whose Redis state is isolated under `namespace`.

        A source that reaches more than one endpoint within a single job — where each
        endpoint stores an incompatible cursor format — uses this to keep their resume
        state in separate slots. Without it a retry that switches endpoints could load a
        cursor the other endpoint wrote and replay it against an API that can't parse it.
        """
        return ResumableSourceManager(self._inputs, self._data_class, namespace=namespace, staged=self._staged)

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
        """One Redis hash per schema, with one field per namespace.

        The key is per schema, not per job, because every scheduled run creates a new job. A per-job
        key means that a run never sees the cursor of the run before it.
        """
        return f"posthog:data_warehouse:resumable_source:schema:{self._inputs.team_id}:{self._inputs.schema_id}"

    @property
    def _field(self) -> str:
        return self._namespace or ""

    @property
    def _legacy_key(self) -> str:
        """The per-job string key that workers wrote before the per-schema hash.

        Read as a fallback, so that a job which is mid-retry during a deploy does not restart.
        """
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
        self._logger.debug(f"Staging resumable source state. key={self._key}, field={self._field}, data={json_data}")
        self._staged[self._field] = json_data

    def has_staged_state(self) -> bool:
        """Whether the next `commit` will write anything."""
        return bool(self._staged)

    def commit(self) -> None:
        """Persist every staged cursor, across namespaces."""
        if not self._staged:
            return
        staged = dict(self._staged)
        with self._get_redis() as redis_client:
            self._logger.debug(f"Saving resumable source state. key={self._key}, data={staged}")

            def write() -> None:
                pipe = redis_client.pipeline()
                pipe.hset(self._key, mapping={**staged, _JOB_ID_FIELD: self._inputs.job_id})
                pipe.expire(self._key, RESUME_STATE_TTL_SECONDS)
                pipe.execute()

            self._write_with_stale_replica_retry(redis_client, write)
            for field in staged:
                self._staged.pop(field, None)

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
        self._staged.pop(self._field, None)
        with self._get_redis() as redis_client:
            self._logger.debug(f"Clearing resumable source state. key={self._key}, field={self._field}")

            def write() -> None:
                redis_client.hdel(self._key, self._field)
                redis_client.delete(self._legacy_key)

            self._write_with_stale_replica_retry(redis_client, write)

    def clear_all_state(self) -> None:
        """Drop the resume state of every namespace of the schema.

        The pipeline calls this after a run completes. The state outlives the job that wrote it,
        so a final cursor that a source did not clear would make the next run skip most of its walk.
        """
        self._staged.clear()
        with self._get_redis() as redis_client:
            self._logger.debug(f"Clearing all resumable source state. key={self._key}")
            self._write_with_stale_replica_retry(redis_client, lambda: redis_client.delete(self._key))

    def discard_state_from_other_jobs(self) -> None:
        """Drop the schema's resume state if a different job wrote it.

        Call this before the source reads any state, for a run that must not continue the walk of an
        earlier run. Retries of this same job keep their state.
        """
        with self._get_redis() as redis_client:
            owner = redis_client.hget(self._key, _JOB_ID_FIELD)
            if isinstance(owner, bytes):
                owner = owner.decode()
            if owner is None or owner == self._inputs.job_id:
                return
            self._logger.debug(f"Discarding resumable source state of another job. key={self._key}, job_id={owner}")
            self._write_with_stale_replica_retry(redis_client, lambda: redis_client.delete(self._key))

    def can_resume(self) -> bool:
        with self._get_redis() as redis:
            exists = bool(redis.hexists(self._key, self._field)) or redis.exists(self._legacy_key) == 1
            self._logger.debug(
                f"Checking resumable source state. key={self._key}, field={self._field}, exists={exists}"
            )

            return exists

    def load_state(self) -> ResumableData | None:
        with self._get_redis() as redis:
            data = redis.hget(self._key, self._field) or redis.get(self._legacy_key)
            if not data:
                self._logger.debug(f"No resumable source state found. key={self._key}")
                return None

            self._logger.debug(f"Loading resumable source state. key={self._key}, data={data}")
            return self._load_json(data)


def resolve_resume_manager(
    manager: ResumableSourceManager[ResumableData] | None,
    resource: SourceResponse,
) -> ResumableSourceManager[ResumableData] | None:
    """Combine the class-level capability (a manager exists) with the run-level one.

    A resumable-source class whose current run can't actually resume — a SQL full load with no
    orderable primary key, say — reports `supports_resume=False` and resolves to `None` here, so it
    is treated as non-resumable everywhere downstream instead of at each call site.
    """
    if manager is None or not resource.supports_resume:
        return None
    return manager
