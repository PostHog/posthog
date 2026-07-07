import json
import dataclasses
from contextlib import contextmanager
from typing import Generic

from django.conf import settings

import orjson
from structlog.types import FilteringBoundLogger

from posthog.redis import get_client

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    ResumableData,
    SourceInputs,
)


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

        return self._data_class(**parsed_data)

    def save_state(self, data: ResumableData) -> None:
        with self._get_redis() as redis:
            json_data = self._dump_json(data)
            self._logger.debug(f"Saving resumable source state. key={self._key}, data={json_data}")

            redis.set(self._key, json_data, ex=60 * 60 * 24)  # 24 hours expiration

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
