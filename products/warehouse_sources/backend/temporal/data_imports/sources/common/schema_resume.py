from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from django.conf import settings

from pydantic import BaseModel, Field, ValidationError
from redis import Redis
from redis.exceptions import ReadOnlyError, WatchError
from structlog.types import FilteringBoundLogger

from posthog.redis import get_client

RESUME_TTL_SECONDS = 24 * 60 * 60


class ResumeWindow(BaseModel):
    incremental_field_last_value: str | int | float | None
    sync_type: str
    incremental_field: str | None
    incremental_field_type: str | None
    source_id: str
    api_version: str | None = None
    source_config_hash: str | None = None


class ResumeCheckpoint(BaseModel):
    cursor: str = Field(repr=False)
    high_water_mark: str | int | float | None
    job_id: str
    job_created_at: datetime
    run_uuid: str
    batch_index: int = Field(ge=0)
    saved_at: datetime


class _SchemaResumeState(BaseModel):
    generation: str
    window: ResumeWindow
    pending: ResumeCheckpoint | None = None
    confirmed: ResumeCheckpoint | None = None


def schema_resume_key(team_id: int, schema_id: str) -> str:
    return f"posthog:data_warehouse:resumable_source:{team_id}:schema:{schema_id}"


def clear_schema_resume_state(*, team_id: int, schema_id: str) -> None:
    if not settings.DATA_WAREHOUSE_REDIS_HOST or not settings.DATA_WAREHOUSE_REDIS_PORT:
        return
    client = get_client(f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/")
    key = schema_resume_key(team_id, schema_id)

    def clear() -> None:
        for _ in range(3):
            try:
                with client.pipeline() as pipe:
                    pipe.watch(f"{key}:keys")
                    reader = cast(Redis, pipe)
                    keys = [
                        name
                        for raw_name in reader.smembers(f"{key}:keys")
                        if (name := raw_name.decode() if isinstance(raw_name, bytes) else raw_name).startswith(
                            f"{key}:namespace:"
                        )
                    ]
                    pipe.multi()
                    pipe.delete(
                        key, f"{key}:generation", f"{key}:keys", *keys, *(f"{name}:generation" for name in keys)
                    )
                    pipe.execute()
                    return
            except WatchError:
                continue
        raise WatchError("Schema resume state changed while resetting the import")

    try:
        clear()
    except ReadOnlyError:
        client.connection_pool.disconnect()
        clear()


class SchemaResumeStore:
    def __init__(
        self,
        *,
        team_id: int,
        schema_id: str,
        job_id: str,
        job_key: str,
        window: ResumeWindow,
        is_durable: Callable[[ResumeCheckpoint], bool],
        logger: FilteringBoundLogger,
        namespace: str | None = None,
    ) -> None:
        self._schema_id = schema_id
        self._team_id = team_id
        self._job_id = job_id
        self._job_key = job_key
        self._window = window
        self._is_durable = is_durable
        self._logger = logger
        base = schema_resume_key(team_id, schema_id)
        self._key = f"{base}:namespace:{namespace}" if namespace else base
        self._generation_key = f"{self._key}:generation"
        self._keys_key = f"{base}:keys"
        self._generation = f"{job_id}:{uuid4()}"
        self.high_water_mark: str | int | float | None = None

    def with_namespace(self, namespace: str, *, job_key: str) -> SchemaResumeStore:
        return SchemaResumeStore(
            team_id=self._team_id,
            schema_id=self._schema_id,
            job_id=self._job_id,
            job_key=job_key,
            window=self._window,
            is_durable=self._is_durable,
            logger=self._logger,
            namespace=namespace,
        )

    def _read_state(self, value: bytes | str | None) -> _SchemaResumeState | None:
        if value is None:
            return None
        try:
            return _SchemaResumeState.model_validate_json(value)
        except ValidationError:
            self._reject("invalid_state")
            return None

    def _reject(self, reason: str) -> None:
        self._logger.info("resume_carry_over_rejected", schema_id=self._schema_id, reason=reason)

    def _window_rejection(self, state: _SchemaResumeState, reset_pipeline: bool) -> str | None:
        if reset_pipeline:
            return "reset_pipeline"
        for field in ResumeWindow.model_fields:
            if getattr(state.window, field) != getattr(self._window, field):
                return f"{field}_changed"
        return None

    @staticmethod
    def _token(value: bytes | str | None) -> str | None:
        return value.decode() if isinstance(value, bytes) else value

    def prepare(self, client: Redis, *, reset_pipeline: bool) -> None:
        for _ in range(3):
            try:
                with client.pipeline() as pipe:
                    pipe.watch(self._generation_key, self._key, self._job_key)
                    reader = cast(Redis, pipe)
                    generation = self._token(reader.get(self._generation_key))
                    state = self._read_state(reader.get(self._key))
                    same_job = bool(reader.exists(self._job_key))
                    if state is not None:
                        reason = self._window_rejection(state, reset_pipeline and not same_job)
                        if state.generation != generation:
                            reason = "generation_changed"
                        if reason is not None:
                            self._reject(reason)
                            state = None

                    checkpoint = None
                    if state is not None:
                        if same_job:
                            checkpoint = state.pending or state.confirmed
                        elif state.pending is not None and self._is_durable(state.pending):
                            checkpoint = state.pending
                        else:
                            checkpoint = state.confirmed
                            if checkpoint is None and state.pending is not None:
                                self._reject("batches_not_loaded")

                    if same_job and generation is not None:
                        if generation.startswith(f"{self._job_id}:"):
                            self._generation = generation
                            self.high_water_mark = checkpoint.high_water_mark if checkpoint else None
                        return

                    pipe.multi()
                    pipe.set(self._generation_key, self._generation, ex=RESUME_TTL_SECONDS)
                    pipe.sadd(self._keys_key, self._key)
                    pipe.expire(self._keys_key, RESUME_TTL_SECONDS)
                    if checkpoint is None:
                        pipe.delete(self._key)
                    else:
                        inherited = _SchemaResumeState(
                            generation=self._generation, window=self._window, confirmed=checkpoint
                        )
                        pipe.set(self._key, inherited.model_dump_json(), ex=RESUME_TTL_SECONDS)
                        pipe.set(self._job_key, checkpoint.cursor, ex=RESUME_TTL_SECONDS)
                    pipe.execute()
                    if checkpoint is not None:
                        self.high_water_mark = checkpoint.high_water_mark
                        self._logger.info(
                            "resume_carried_over",
                            schema_id=self._schema_id,
                            cursor_age_seconds=max(0, (datetime.now(UTC) - checkpoint.saved_at).total_seconds()),
                            stored_window=self._window.incremental_field_last_value,
                        )
                    return
            except WatchError:
                continue
        raise WatchError("Schema resume state changed while starting the import")

    def restart(self, client: Redis) -> None:
        self._generation = f"{self._job_id}:{uuid4()}"
        self.high_water_mark = None
        with client.pipeline() as pipe:
            pipe.set(self._generation_key, self._generation, ex=RESUME_TTL_SECONDS)
            pipe.delete(self._key)
            pipe.execute()

    def commit(self, client: Redis, checkpoint: ResumeCheckpoint) -> None:
        for _ in range(3):
            try:
                with client.pipeline() as pipe:
                    pipe.watch(self._generation_key, self._key)
                    reader = cast(Redis, pipe)
                    if self._token(reader.get(self._generation_key)) != self._generation:
                        pipe.unwatch()
                        client.set(self._job_key, checkpoint.cursor, ex=RESUME_TTL_SECONDS)
                        return
                    state = self._read_state(reader.get(self._key))
                    confirmed = None
                    if state is not None and state.generation == self._generation and state.window == self._window:
                        confirmed = state.confirmed
                        if state.pending is not None and self._is_durable(state.pending):
                            confirmed = state.pending

                    # Keep a loaded checkpoint when a failed append job discards its newest queued batch.
                    updated = _SchemaResumeState(
                        generation=self._generation, window=self._window, pending=checkpoint, confirmed=confirmed
                    )
                    pipe.multi()
                    pipe.set(self._job_key, checkpoint.cursor, ex=RESUME_TTL_SECONDS)
                    pipe.set(self._key, updated.model_dump_json(), ex=RESUME_TTL_SECONDS)
                    pipe.expire(self._generation_key, RESUME_TTL_SECONDS)
                    pipe.sadd(self._keys_key, self._key)
                    pipe.expire(self._keys_key, RESUME_TTL_SECONDS)
                    pipe.execute()
                    return
            except WatchError:
                continue
        raise WatchError("Schema resume state changed while saving the checkpoint")

    def clear(self, client: Redis) -> None:
        for _ in range(3):
            try:
                with client.pipeline() as pipe:
                    pipe.watch(self._generation_key)
                    owns_state = self._token(cast(Redis, pipe).get(self._generation_key)) == self._generation
                    pipe.multi()
                    pipe.delete(self._job_key)
                    if owns_state:
                        pipe.delete(self._key)
                        pipe.srem(self._keys_key, self._key)
                    pipe.execute()
                    return
            except WatchError:
                continue
        raise WatchError("Schema resume state changed while clearing the checkpoint")
