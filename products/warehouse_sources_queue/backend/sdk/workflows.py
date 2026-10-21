"""Workflows: durable async functions made of checkpointed steps.

A workflow is one ``async def`` per job kind. The engine runs it again on each attempt of the
job. Inside it, ``await ctx.step("key", fn, ...)`` runs ``fn`` once and stores its result in
``queuejobstep``. On a later attempt (after a retry, a crash, or a shutdown) a completed step
returns its stored result and does not run again. Steps are keyed by name, not by position, so a
deploy can add steps: a renamed step is a new step. ``ctx.started_version`` is the workflow
version that ran the job's first attempt, for a change that is not additive.

``WorkflowHandler`` implements ``JobHandler``, so a ``JobConsumer`` runs a workflow with no
engine change: ``JobConsumer(handlers={sync.kind: WorkflowHandler(sync)}, ...)``.
"""

from __future__ import annotations

import json
import typing
import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Generic, Literal, Protocol, TypeVar, cast

import psycopg
import pydantic
from pydantic_core import PydanticSerializationError

from posthog.dataclasses import frozen

from products.warehouse_sources_queue.backend.core.batch_consumer import OwnershipLostError
from products.warehouse_sources_queue.backend.core.generic_jobs import Job
from products.warehouse_sources_queue.backend.core.job_steps import (
    STEP_KEY_MAX_LENGTH,
    JobStepsTable,
    StepRecord,
    StepState,
)
from products.warehouse_sources_queue.backend.sdk.jobs import Fail, JobContext, Outcome, Retry, Success

logger = logging.getLogger(__name__)

P = TypeVar("P")
R = TypeVar("R")

# Large outputs go by reference (an S3 key, a row id). The step table stays small and cheap.
STEP_RESULT_MAX_BYTES = 32 * 1024
# The SDK's own row that keeps the version of the job's first attempt.
STARTED_STEP_KEY = "__started__"
_RESERVED_STEP_KEY_PREFIX = "__"
_FAIL_REASON_MAX_LENGTH = 1000

OnFailure = Literal["fail_job", "retry_job", "continue"]


@frozen
class StepPolicy:
    """How one step retries and what happens when it runs out of attempts.

    ``max_attempts`` counts the failed executions of the step over all attempts of the job.
    ``on_failure``:

    - ``"fail_job"``: retry the step at once in the same attempt, after ``retry_delay`` times the
      failure count. After the last failure, raise ``StepFailed`` (the job fails unless the
      workflow catches it).
    - ``"retry_job"``: end the job attempt with a retry, so the step runs again on the next
      attempt after the engine's backoff. Use it for long steps that must start fresh. After the
      last failure, raise ``StepFailed``.
    - ``"continue"``: retry as ``"fail_job"`` does. After the last failure, record the step as
      skipped and return None.

    A crash in the middle of a step records no failure. The engine's own attempt cap covers it.
    """

    max_attempts: int = 1
    timeout: timedelta | None = None
    on_failure: OnFailure = "fail_job"
    retry_delay: timedelta = timedelta(seconds=1)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("StepPolicy.max_attempts must be 1 or more")


DEFAULT_STEP_POLICY = StepPolicy()


class WorkflowRetry(Exception):
    """Raise from workflow code or from a step to end this attempt with a retry.

    A step that raises it records nothing, so the step runs again on the next attempt. ``tag``
    goes on the retry's status row (see ``JobContext.retry_history``).
    """

    def __init__(self, reason: str = "the workflow asked for a retry", *, tag: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.tag = tag


class StepFailed(Exception):
    """A step failed for the last time. Uncaught, it fails the job."""

    def __init__(self, key: str, *, failures: int, error: str | None) -> None:
        super().__init__(f"step {key!r} failed {failures} time(s): {error}")
        self.key = key
        self.failures = failures
        self.error = error


class NonRetryableStepError(Exception):
    """Raise from a step to use up its remaining attempts: the step gives up at once."""


class StepResultError(Exception):
    """A step returned a value that the SDK cannot store. Fix the step; a retry does not help."""


class StepKeyError(ValueError):
    """A step key is empty, too long, reserved, or used twice in one attempt."""


class Clock(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class StepHooks(Protocol):
    """Test seam: the test runner swaps step functions and watches checkpoints through it."""

    def resolve(self, key: str, fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]: ...

    def recorded(self, record: StepRecord) -> None: ...


class _StepStoreUnavailable(Exception):
    """The queue database refused a step read or write. The attempt retries."""


class _StepTimedOut(Exception):
    pass


@lru_cache(maxsize=1024)
def _type_adapter(tp: Any) -> pydantic.TypeAdapter[Any]:
    return pydantic.TypeAdapter(tp)


def _result_adapter(fn: Callable[..., Any]) -> pydantic.TypeAdapter[Any]:
    """The codec for a step's result, from the step function's return annotation."""
    try:
        return_type = typing.get_type_hints(fn).get("return", Any)
        return _type_adapter(return_type)
    except Exception:
        # No usable annotation (a partial, a lambda, a forward reference): store plain JSON.
        return _type_adapter(Any)


def _encode_result(key: str, fn: Callable[..., Any], value: Any) -> str:
    try:
        encoded = _result_adapter(fn).dump_json(value)
    except PydanticSerializationError as err:
        raise StepResultError(f"step {key!r} returned a value that is not JSON-serializable: {err}") from err
    if len(encoded) > STEP_RESULT_MAX_BYTES:
        raise StepResultError(
            f"step {key!r} returned {len(encoded)} bytes of JSON, more than the {STEP_RESULT_MAX_BYTES} byte limit. "
            "Store a large output somewhere else (S3, a table) and return a reference to it."
        )
    return encoded.decode()


def _decode_result(key: str, fn: Callable[..., Any], data: Any) -> Any:
    try:
        return _result_adapter(fn).validate_python(data)
    except pydantic.ValidationError as err:
        raise StepResultError(f"step {key!r}: the stored result does not match the return annotation: {err}") from err


def _describe(err: BaseException) -> str:
    return f"{type(err).__name__}: {err}"


@frozen(slots=False)
class WorkflowDefinition(Generic[P]):
    """What ``@workflow`` returns. Give it to ``WorkflowHandler`` to run it on a consumer."""

    kind: str
    lane: str
    version: str
    payload_type: type[P]
    run: Callable[[WorkflowContext[P]], Awaitable[None]]
    # Called when the engine fails the job without the workflow (attempt cap, claim deadline),
    # so the workflow can finish the external state that it owns.
    on_engine_failed: Callable[[Job, str], Awaitable[None]] | None = None

    def decode_payload(self, data: Mapping[str, Any]) -> P:
        return cast(P, _type_adapter(self.payload_type).validate_python(data))

    def encode_payload(self, payload: P) -> dict[str, Any]:
        """The JSON payload to enqueue for this workflow (``JobsTable.insert(payload=...)``)."""
        return cast(dict[str, Any], _type_adapter(self.payload_type).dump_python(payload, mode="json"))


_WORKFLOWS: dict[str, WorkflowDefinition[Any]] = {}


def workflow(
    *,
    kind: str,
    lane: str,
    payload: type[P],
    version: str = "1",
    on_engine_failed: Callable[[Job, str], Awaitable[None]] | None = None,
) -> Callable[[Callable[[WorkflowContext[P]], Awaitable[None]]], WorkflowDefinition[P]]:
    """Declare a workflow for one job kind.

    ``payload`` is the type of ``ctx.payload``: a dataclass, a pydantic model, or a ``dict``.
    Change ``version`` when a change is not additive, and branch on ``ctx.started_version``.
    """

    def decorate(fn: Callable[[WorkflowContext[P]], Awaitable[None]]) -> WorkflowDefinition[P]:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"@workflow({kind!r}) needs an async def, not {fn!r}")
        definition = WorkflowDefinition(
            kind=kind, lane=lane, version=version, payload_type=payload, run=fn, on_engine_failed=on_engine_failed
        )
        existing = _WORKFLOWS.get(kind)
        # A module that is imported again registers the same function again, which is safe.
        if existing is not None and (existing.run.__module__, existing.run.__qualname__) != (
            fn.__module__,
            fn.__qualname__,
        ):
            raise ValueError(
                f"workflow kind {kind!r} is already registered by {existing.run.__module__}.{existing.run.__qualname__}"
            )
        _WORKFLOWS[kind] = definition
        return definition

    return decorate


def get_workflow(kind: str) -> WorkflowDefinition[Any]:
    try:
        return _WORKFLOWS[kind]
    except KeyError:
        raise KeyError(f"no workflow is registered for kind {kind!r}; import the module that declares it") from None


class _StepStore:
    """Short-lived connections, so a step that runs for hours holds no idle connection."""

    def __init__(self, database_url: str, job: Job) -> None:
        self._database_url = database_url
        self._job = job

    async def load(self) -> list[StepRecord]:
        try:
            async with await psycopg.AsyncConnection.connect(self._database_url, autocommit=True) as conn:
                return await JobStepsTable.load(conn, job_id=self._job.id, job_created_at=self._job.created_at)
        except psycopg.OperationalError as err:
            raise _StepStoreUnavailable(_describe(err)) from err

    async def record(self, record: StepRecord, encoded_result: str | None = None) -> None:
        try:
            async with await psycopg.AsyncConnection.connect(self._database_url, autocommit=True) as conn:
                await JobStepsTable.record(
                    conn,
                    job_id=self._job.id,
                    job_created_at=self._job.created_at,
                    record=record,
                    encoded_result=encoded_result,
                )
        except psycopg.OperationalError as err:
            raise _StepStoreUnavailable(_describe(err)) from err


class WorkflowContext(Generic[P]):
    """What a workflow function gets: its payload, its job, and ``step``."""

    def __init__(
        self,
        *,
        job: Job,
        payload: P,
        attempt: int,
        started_version: str,
        logger: logging.Logger,
        shutdown_event: asyncio.Event,
        records: list[StepRecord],
        store: _StepStore,
        clock: Clock,
        hooks: StepHooks | None,
    ) -> None:
        self.job = job
        self.payload = payload
        # The job attempt that runs now. The first attempt is 1.
        self.attempt = attempt
        self.started_version = started_version
        self.logger = logger
        # Set when the consumer starts to shut down. A long step watches it and raises WorkflowRetry.
        self.shutdown_event = shutdown_event
        self._store = store
        self._clock = clock
        self._hooks = hooks
        self._completed: dict[str, StepRecord] = {}
        self._failures: dict[str, int] = {}
        self._last_errors: dict[str, str | None] = {}
        self._keys_this_attempt: set[str] = set()
        for record in records:
            if record.state is StepState.FAILED:
                self._failures[record.key] = self._failures.get(record.key, 0) + 1
                self._last_errors[record.key] = record.error
            else:
                self._completed[record.key] = record

    async def step(
        self,
        key: str,
        fn: Callable[..., Awaitable[R]],
        *args: Any,
        policy: StepPolicy = DEFAULT_STEP_POLICY,
        **kwargs: Any,
    ) -> R:
        """Run ``fn(*args, **kwargs)`` once for this job and return its result.

        A step that completed on an earlier attempt returns its stored result and does not run.
        The result must be JSON-serializable through the return annotation of ``fn`` (a
        dataclass, a pydantic model, primitives, lists and dicts of them) and at most 32 KB.
        With ``on_failure="continue"`` a step that gives up returns None, so annotate ``fn`` as
        returning ``X | None``.
        """
        self._claim_key(key, fn)
        completed = self._completed.get(key)
        if completed is not None:
            if completed.state is StepState.SKIPPED:
                return cast(R, None)
            return cast(R, _decode_result(key, fn, completed.result))

        while True:
            failures = self._failures.get(key, 0)
            if failures >= policy.max_attempts:
                return cast(R, await self._give_up(key, policy))
            started_at = self._clock.now()
            try:
                value = await self._execute(key, fn, args, kwargs, policy)
            except WorkflowRetry:
                raise
            except Exception as err:
                error = f"step timed out after {policy.timeout}" if isinstance(err, _StepTimedOut) else _describe(err)
                await self._record(key, StepState.FAILED, started_at, error=error)
                failures += 1
                self._failures[key] = failures
                self._last_errors[key] = error
                self.logger.warning(
                    "workflow_step_failed",
                    extra={"job_id": self.job.id, "step": key, "failures": failures, "error": error},
                )
                if isinstance(err, NonRetryableStepError) or failures >= policy.max_attempts:
                    return cast(R, await self._give_up(key, policy))
                if policy.on_failure == "retry_job":
                    raise WorkflowRetry(
                        f"step {key!r} failed ({failures} of {policy.max_attempts}): {error}"[:_FAIL_REASON_MAX_LENGTH]
                    ) from err
                await self._clock.sleep(policy.retry_delay.total_seconds() * failures)
                continue

            encoded = _encode_result(key, fn, value)
            stored = json.loads(encoded)
            # Decode before the checkpoint, so a result that cannot round-trip fails now and not
            # on a rare later attempt.
            decoded = _decode_result(key, fn, stored)
            await self._record(key, StepState.SUCCEEDED, started_at, result=stored, encoded_result=encoded)
            return cast(R, decoded)

    def _claim_key(self, key: str, fn: Callable[..., Any]) -> None:
        if not key or len(key) > STEP_KEY_MAX_LENGTH:
            raise StepKeyError(f"a step key must have 1 to {STEP_KEY_MAX_LENGTH} characters, got {key!r}")
        if key.startswith(_RESERVED_STEP_KEY_PREFIX):
            raise StepKeyError(f"step keys that start with {_RESERVED_STEP_KEY_PREFIX!r} are reserved, got {key!r}")
        if key in self._keys_this_attempt:
            raise StepKeyError(
                f"step key {key!r} is already used in this run; give each call its own key, such as f'{key}:{{n}}'"
            )
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"step {key!r} needs an async function, not {fn!r}")
        self._keys_this_attempt.add(key)

    async def _execute(
        self,
        key: str,
        fn: Callable[..., Awaitable[R]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        policy: StepPolicy,
    ) -> R:
        call = self._hooks.resolve(key, fn) if self._hooks is not None else fn
        if policy.timeout is None:
            return await call(*args, **kwargs)
        try:
            async with asyncio.timeout(policy.timeout.total_seconds()) as scope:
                return await call(*args, **kwargs)
        except TimeoutError:
            # Only our own deadline is a timeout. A TimeoutError from inside the step is its own error.
            if scope.expired():
                raise _StepTimedOut() from None
            raise

    async def _give_up(self, key: str, policy: StepPolicy) -> None:
        if policy.on_failure == "continue":
            await self._record(key, StepState.SKIPPED, self._clock.now(), error=self._last_errors.get(key))
            return None
        raise StepFailed(key, failures=self._failures.get(key, 0), error=self._last_errors.get(key))

    async def _record(
        self,
        key: str,
        state: StepState,
        started_at: datetime,
        *,
        result: Any = None,
        encoded_result: str | None = None,
        error: str | None = None,
    ) -> None:
        record = StepRecord(
            key=key,
            state=state,
            job_attempt=self.attempt,
            started_at=started_at,
            ended_at=self._clock.now(),
            result=result,
            error=error,
        )
        await self._store.record(record, encoded_result)
        if state is not StepState.FAILED:
            self._completed[key] = record
        if self._hooks is not None:
            self._hooks.recorded(record)


class WorkflowHandler:
    """Runs a workflow as a ``JobHandler`` (and ``EngineFailureHandler``).

    Outcomes: a return is ``Success``; ``WorkflowRetry`` is ``Retry``; ``StepFailed`` and any
    other error are ``Fail``. A lost lease propagates, so the engine abandons the attempt.
    """

    def __init__(
        self,
        definition: WorkflowDefinition[Any],
        *,
        clock: Clock | None = None,
        hooks: StepHooks | None = None,
    ) -> None:
        self.definition = definition
        self._clock: Clock = clock or SystemClock()
        self._hooks = hooks

    async def handle(self, job: Job, ctx: JobContext) -> Outcome:
        definition = self.definition
        try:
            payload = definition.decode_payload(job.payload)
        except pydantic.ValidationError as err:
            return Fail(reason=f"payload does not match {definition.payload_type!r}: {err}"[:_FAIL_REASON_MAX_LENGTH])

        try:
            workflow_ctx = await self._context(job, ctx, payload)
            await definition.run(workflow_ctx)
        except OwnershipLostError:
            raise
        except WorkflowRetry as retry:
            return Retry(reason=retry.reason, tag=retry.tag)
        except _StepStoreUnavailable as err:
            return Retry(reason=f"the step store is unavailable: {err}"[:_FAIL_REASON_MAX_LENGTH])
        except StepFailed as err:
            ctx.logger.warning("workflow_failed", extra={"job_id": job.id, "kind": job.kind, "error": str(err)})
            return Fail(reason=str(err)[:_FAIL_REASON_MAX_LENGTH])
        except Exception as err:
            ctx.logger.exception("workflow_failed", extra={"job_id": job.id, "kind": job.kind})
            return Fail(reason=_describe(err)[:_FAIL_REASON_MAX_LENGTH])
        return Success()

    async def on_engine_failed(self, job: Job, reason: str) -> None:
        if self.definition.on_engine_failed is not None:
            await self.definition.on_engine_failed(job, reason)

    async def _context(self, job: Job, ctx: JobContext, payload: Any) -> WorkflowContext[Any]:
        attempt = job.latest_attempt + 1
        store = _StepStore(ctx.database_url, job)
        records = await store.load()
        started = next((r for r in records if r.key == STARTED_STEP_KEY), None)
        if started is None:
            started_version = self.definition.version
            now = self._clock.now()
            await store.record(
                StepRecord(
                    key=STARTED_STEP_KEY,
                    state=StepState.SUCCEEDED,
                    job_attempt=attempt,
                    started_at=now,
                    ended_at=now,
                    result={"version": started_version},
                    error=None,
                ),
                json.dumps({"version": started_version}),
            )
        else:
            started_version = str(started.result["version"])
        return WorkflowContext(
            job=job,
            payload=payload,
            attempt=attempt,
            started_version=started_version,
            logger=ctx.logger,
            shutdown_event=ctx.shutdown_event,
            records=[r for r in records if r.key != STARTED_STEP_KEY],
            store=store,
            clock=self._clock,
            hooks=self._hooks,
        )
