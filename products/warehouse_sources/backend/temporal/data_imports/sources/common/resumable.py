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
    def _base_key(self) -> str:
        # Keyed by the stable (team, source, endpoint) identity, not the per-run job id. A
        # restarted sync gets a fresh job id, so a job-scoped key orphaned the previous run's
        # checkpoint and forced a full re-walk. `schema_id` is the endpoint: one schema per table.
        base = (
            "posthog:data_warehouse:resumable_source:"
            f"{self._inputs.team_id}:{self._inputs.source_id}:{self._inputs.schema_id}"
        )
        # The vendor API version is part of the identity: a repinned version cancels the running
        # job, so resuming its cursor against the new version would mix two versions in one table.
        if self._inputs.api_version:
            base = f"{base}:v={self._inputs.api_version}"
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

            redis.set(self._key, json_data, ex=RESUMABLE_STATE_TTL_SECONDS)

    def clear_state(self) -> None:
        """Drop any saved resume state so a subsequent attempt starts from scratch.

        Called once a source has walked its data to completion: leaving the final checkpoint in
        place would let a later attempt resume mid-stream instead of restarting cleanly.
        """
        with self._get_redis() as redis:
            self._logger.debug(f"Clearing resumable source state. key={self._key}")
            redis.delete(self._key)

    def clear_all_state(self) -> None:
        """Drop this schema's checkpoint and every `with_namespace` sibling of it.

        The stable key outlives a run, so a checkpoint left by a completed or killed walk stays
        readable by the next run. When the pipeline finishes a walk, it must delete every key for the
        schema, including the namespaced siblings a source writes through `with_namespace` (Convex)
        that `clear_state` on the base manager would miss. Otherwise a later run resumes stale rows
        onto a fresh table and the sync truncates silently.
        """
        with self._get_redis() as redis:
            self._logger.debug(f"Clearing all resumable source state. base={self._base_key}")
            redis.delete(self._base_key)
            for key in redis.scan_iter(match=f"{self._base_key}:*", count=100):
                redis.delete(key)

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
