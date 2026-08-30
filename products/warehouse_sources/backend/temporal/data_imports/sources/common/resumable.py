import json
import dataclasses
from contextlib import contextmanager
from typing import Generic

from django.conf import settings

import orjson
from structlog.types import FilteringBoundLogger

from posthog.redis import get_client

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import ResumableData, SourceInputs

# A resumable source's import activity can run up to a week (`start_to_close_timeout`), so a
# checkpoint must outlive that worst case for a killed run to resume on its next attempt. A run that
# walks to completion clears its own state, so this TTL only bounds abandoned checkpoints.
RESUMABLE_STATE_TTL_SECONDS = 60 * 60 * 24 * 14  # 14 days


class ResumableSourceManager(Generic[ResumableData]):
    _inputs: SourceInputs
    _data_class: type[ResumableData]
    _logger: FilteringBoundLogger
    _namespace: str | None

    def __init__(self, inputs: SourceInputs, data_class: type[ResumableData], namespace: str | None = None):
        self._inputs = inputs
        self._data_class = data_class
        self._logger = inputs.logger
        self._namespace = namespace

    def with_namespace(self, namespace: str) -> "ResumableSourceManager[ResumableData]":
        """Return a sibling manager whose Redis state is isolated under `namespace`.

        A source that reaches more than one endpoint within a single job — where each
        endpoint stores an incompatible cursor format — uses this to keep their resume
        state in separate slots. Without it a retry that switches endpoints could load a
        cursor the other endpoint wrote and replay it against an API that can't parse it.
        """
        return ResumableSourceManager(self._inputs, self._data_class, namespace=namespace)

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
    def _schema_identity(self) -> str:
        return f"{self._inputs.team_id}:{self._inputs.source_id}:{self._inputs.schema_id}"

    @property
    def _schema_key_prefix(self) -> str:
        # Version-neutral identity of this schema's checkpoints. Reads and writes scope tighter, by
        # API version (see `_base_key`), so a resume never mixes versions.
        return f"posthog:data_warehouse:resumable_source:{self._schema_identity}"

    @property
    def _index_key(self) -> str:
        # Set naming every checkpoint key this schema owns, across API versions and `with_namespace`
        # siblings, so `clear_all_state` can reach them all without walking the Redis keyspace.
        # Deliberately outside `_schema_key_prefix`: a sibling appends its namespace to that prefix,
        # so an index stored under it could collide with a namespace of the same name.
        return f"posthog:data_warehouse:resumable_source_index:{self._schema_identity}"

    @property
    def _base_key(self) -> str:
        # Keyed by the stable (team, source, endpoint) identity, not the per-run job id. A
        # restarted sync gets a fresh job id, so a job-scoped key orphaned the previous run's
        # checkpoint and forced a full re-walk. `schema_id` is the endpoint: one schema per table.
        base = self._schema_key_prefix
        # The vendor API version is part of the identity: a repinned version cancels the running
        # job, so resuming its cursor against the new version would mix two versions in one table.
        if self._inputs.api_version:
            base = f"{base}:v={self._inputs.api_version}"
        # So is the connection target. Repointing a source keeps the same ids, so without this the
        # next run would replay a cursor — often a whole URL — captured against the old target,
        # landing two upstreams' rows in one table with the new target's early pages never fetched.
        if self._inputs.connection_target:
            base = f"{base}:c={self._inputs.connection_target}"
        return base

    @property
    def _key(self) -> str:
        return f"{self._base_key}:{self._namespace}" if self._namespace else self._base_key

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

        return self._data_class(**parsed_data)

    def save_state(self, data: ResumableData) -> None:
        if self._inputs.reset_pipeline:
            # A reset is a full re-pull. Now that the key is stable across runs, a checkpoint left
            # here would let a later attempt resume mid-stream onto a wiped table and truncate it.
            return

        with self._get_redis() as redis:
            json_data = self._dump_json(data)
            self._logger.debug(f"Saving resumable source state. key={self._key}, data={json_data}")

            pipeline = redis.pipeline()
            pipeline.set(self._key, json_data, ex=RESUMABLE_STATE_TTL_SECONDS)
            pipeline.sadd(self._index_key, self._key)
            # Refreshed on every write, so the index always outlives the keys it names — each was
            # written no later than this, under the same TTL. An index that expired first would
            # strand its checkpoints past a cleanup that can no longer see them.
            pipeline.expire(self._index_key, RESUMABLE_STATE_TTL_SECONDS)
            pipeline.execute()

    def clear_state(self) -> None:
        """Drop any saved resume state so a subsequent attempt starts from scratch.

        Called once a source has walked its data to completion: leaving the final checkpoint in
        place would let a later attempt resume mid-stream instead of restarting cleanly.
        """
        with self._get_redis() as redis:
            self._logger.debug(f"Clearing resumable source state. key={self._key}")
            pipeline = redis.pipeline()
            pipeline.delete(self._key)
            pipeline.srem(self._index_key, self._key)
            pipeline.execute()

    def clear_all_state(self) -> None:
        """Drop every checkpoint for this schema: all API versions and every `with_namespace` sibling.

        The stable key outlives a run, so a checkpoint left by a completed or killed walk stays
        readable by the next run. Reads and writes are version-scoped so a resume never mixes
        versions, but cleanup must reach every version. A walk clears only the version pinned now, so
        a checkpoint left under a prior pin survives a repin from A to B and back to A within the TTL,
        and the return-to-A run resumes its stale cursor onto a table it should full-refresh, keeping
        only the tail. Working off the index also catches the namespaced siblings a source writes
        through `with_namespace` (Convex) that a version-scoped clear would miss.

        This runs on every completed resumable sync and every reset, so it reads the schema's own
        index rather than matching a prefix: a `SCAN` visits every key in the database, which on a
        deployment sharing Redis with the rest of PostHog costs far more than the handful of
        checkpoints a schema actually owns.
        """
        with self._get_redis() as redis:
            keys = redis.smembers(self._index_key)
            self._logger.debug(f"Clearing all resumable source state. index={self._index_key}, keys={len(keys)}")
            redis.delete(*keys, self._index_key)

    def discard_stale_state_on_reset(self) -> None:
        """Drop every saved checkpoint when this run is a reset, called before the reset wipes the table.

        A reset re-pulls from scratch. The key is stable across runs now, so a checkpoint left by a
        prior killed run would survive the reset and let a later non-reset run — this job's own retry
        once `reset_pipeline` is popped from the schema, or the next scheduled run — resume from the
        pre-reset cursor onto the wiped table, silently keeping only the tail of the source. On a
        non-reset run this is a no-op; `save_state` stays disabled during a reset, so none is rewritten.
        """
        if not self._inputs.reset_pipeline:
            return

        self.clear_all_state()

    def can_resume(self) -> bool:
        if self._inputs.reset_pipeline:
            # A reset always restarts from the first page, so never resume a prior checkpoint.
            return False

        with self._get_redis() as redis:
            exists = redis.exists(self._key) == 1
            self._logger.debug(f"Checking resumable source state. key={self._key}, exists={exists}")

            return exists

    def load_state(self) -> ResumableData | None:
        if self._inputs.reset_pipeline:
            return None

        with self._get_redis() as redis:
            data = redis.get(self._key)
            if not data:
                self._logger.debug(f"No resumable source state found. key={self._key}")
                return None

            self._logger.debug(f"Loading resumable source state. key={self._key}, data={data}")
            return self._load_json(data)
