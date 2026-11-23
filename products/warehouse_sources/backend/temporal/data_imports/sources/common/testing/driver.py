import io
import asyncio
import datetime
import contextlib
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import Any

import orjson
import pyarrow as pa
import pyarrow.parquet as pq

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common import webhook_s3
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ResumableSource,
    SimpleSource,
    _BaseSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.fake_network import (
    SCRIPTED_REQUEST_LIMIT,
    RecordedRequest,
    RunStopped,
    fake_environment,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.inputs import source_inputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.responders import (
    Script,
    ScriptedResponder,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager


@frozen
class DriveResult:
    """What one extraction did, as a test can assert on it."""

    # Each row the source handed the pipeline, with a page of rows flattened into its rows.
    rows: list[Any]
    # What the source yielded, unflattened, for a test that cares about page boundaries.
    items: list[Any]
    requests: list[RecordedRequest]
    # Every cursor the source saved, in order, whether or not it persisted.
    saved_states: list[Any]
    # Each cursor that reached storage, so a cursor saved after the last row does not appear.
    committed_states: list[Any]
    # The cursor left in storage when the run ended. None when the source cleared it, or never saved one.
    final_state: Any
    # The cursor left after the pipeline ran the response's `on_complete` hook, which it does only
    # after a clean run. Equal to `final_state` when the run raised or the response has no hook.
    completed_state: Any
    raised: BaseException | None
    # What `source_for_pipeline` returned: the name, the keys, the partitioning and the sort mode.
    response: SourceResponse | None
    # The keyword arguments of each `make_tracked_session` call, such as `redact_values`.
    session_options: list[dict[str, Any]]

    @property
    def urls(self) -> list[str]:
        return [request.url for request in self.requests]

    @property
    def queries(self) -> list[dict[str, tuple[str, ...]]]:
        return [dict(request.query) for request in self.requests]

    @property
    def paths(self) -> list[str]:
        """Each request's path, without the origin or the query string."""
        return [request.path for request in self.requests]

    def params(self, name: str) -> list[str | None]:
        """The value of one query parameter across the requests, in order."""
        return [request.param(name) for request in self.requests]


class SourceDriver:
    """Runs a source against scripted vendor answers, with no network and no database.

    It drives `source_for_pipeline`, the entry point the pipeline itself calls, so a run covers the
    source's config and inputs plumbing as well as its fetching. It also stands in for the pipeline
    around the run: it commits the resume cursor when the source hands over a row or reaches a safe
    point, which is what makes a cursor saved after the last row fail to persist, as in production.

    The schema is a webhook schema only when the driver is given `webhook_files`. Otherwise a source that
    can read webhook rows polls the API instead, as it does before its webhook is live.
    """

    def __init__(
        self, source: _BaseSource[Any], config: Any, *, webhook_files: Sequence[Sequence[dict[str, Any]]] | None = None
    ) -> None:
        """`webhook_files` turns the webhook on and stages each list of payloads as one file, in arrival order."""
        self._source = source
        self._config = config
        self._webhook_files = webhook_files

    def run(
        self,
        schema_name: str,
        script: Script,
        *,
        resume_state: Any = None,
        **inputs: Any,
    ) -> DriveResult:
        """Run one extraction to its end or its first error.

        `script` answers the requests, in order or by request. `resume_state` is a cursor a previous
        attempt left behind, so the source resumes from it. Other keywords go to `source_inputs`.
        """
        with fake_environment(ScriptedResponder(script), SCRIPTED_REQUEST_LIMIT) as network:
            built = source_inputs(schema_name, **inputs)
            saved: list[Any] = []
            committed: list[Any] = []
            rows: list[Any] = []
            items: list[Any] = []
            raised: BaseException | None = None
            response: SourceResponse | None = None

            with (
                self._recording_saves(saved),
                _webhooks_off() if self._webhook_files is None else _staged_webhook_files(built, self._webhook_files),
            ):
                manager = self._manager(built)
                if manager is not None and resume_state is not None:
                    manager.save_state(resume_state)
                    manager.confirm()
                    manager.commit()
                    saved.clear()

                def hand_over() -> None:
                    """Stand in for the pipeline after a write: stage the cursor and persist it."""
                    network.note_progress()
                    if manager is None:
                        return
                    manager.confirm()
                    manager.commit()
                    state = manager.load_state()
                    if state is not None and (not committed or committed[-1] != state):
                        committed.append(state)

                try:
                    response = self._start(built, manager)
                    emitted = response.items()
                    with contextlib.ExitStack() as stack:
                        if manager is not None:
                            stack.enter_context(
                                activate_safe_point(
                                    hand_over, covers_framework_checkpoints=isinstance(emitted, Resource)
                                )
                            )

                        def take(item: Any) -> None:
                            items.append(item)
                            if isinstance(item, list | tuple):
                                rows.extend(item)
                            else:
                                rows.append(item)
                            hand_over()

                        _consume(emitted, take)
                except (Exception, RunStopped) as error:
                    raised = error

                final_state = manager.load_state() if manager is not None else None
                completed_state = final_state
                if raised is None and response is not None and response.on_complete is not None:
                    response.on_complete()
                    completed_state = manager.load_state() if manager is not None else None

            return DriveResult(
                rows=rows,
                items=items,
                requests=list(network.requests_log),
                saved_states=saved,
                committed_states=committed,
                final_state=final_state,
                completed_state=completed_state,
                raised=raised,
                response=response,
                session_options=list(network.session_options),
            )

    def _manager(self, inputs: SourceInputs) -> ResumableSourceManager[Any] | None:
        if isinstance(self._source, ResumableSource):
            return self._source.get_resumable_source_manager(inputs)
        return None

    def _start(self, inputs: SourceInputs, manager: ResumableSourceManager[Any] | None) -> Any:
        if manager is not None:
            assert isinstance(self._source, ResumableSource)
            return self._source.source_for_pipeline(self._config, manager, inputs)
        assert isinstance(self._source, SimpleSource)
        return self._source.source_for_pipeline(self._config, inputs)

    @staticmethod
    @contextlib.contextmanager
    def _recording_saves(saved: list[Any]) -> Iterator[None]:
        """Record every cursor a source saves, including on a sibling from `with_namespace`."""
        original = ResumableSourceManager.save_state

        def save_state(self: ResumableSourceManager[Any], data: Any) -> None:
            saved.append(data)
            original(self, data)

        with contextlib.ExitStack() as stack:
            stack.enter_context(_patched(ResumableSourceManager, "save_state", save_state))
            yield


_REAL_WEBHOOK_CHECKS = {
    "webhook_enabled": WebhookSourceManager.webhook_enabled,
    "schema_is_webhook": WebhookSourceManager.schema_is_webhook,
}


@contextlib.contextmanager
def _webhooks_off() -> Iterator[None]:
    """Answer the webhook checks as for a schema with no webhook, which they otherwise read from the database.

    A check a test has patched itself, for example to turn the webhook on, keeps the test's answer.
    """

    async def no_webhook(self: WebhookSourceManager, *args: Any, **kwargs: Any) -> bool:
        return False

    with contextlib.ExitStack() as stack:
        for name, real in _REAL_WEBHOOK_CHECKS.items():
            if getattr(WebhookSourceManager, name) is real:
                stack.enter_context(_patched(WebhookSourceManager, name, no_webhook))
        yield


class _StagedWebhookFiles:
    """The webhook folder of one schema in S3, holding the given files a minute apart."""

    _FIRST_MODIFIED = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)

    def __init__(self, inputs: SourceInputs, files: Sequence[Sequence[dict[str, Any]]]) -> None:
        self._folder = webhook_s3._webhook_folder(inputs.team_id, inputs.schema_id)
        self._files: dict[str, tuple[datetime.datetime, bytes]] = {}
        for index, payloads in enumerate(files):
            table = pa.table(
                {
                    "team_id": pa.array([inputs.team_id] * len(payloads), pa.int64()),
                    "schema_id": pa.array([str(inputs.schema_id)] * len(payloads), pa.string()),
                    "payload_json": pa.array([orjson.dumps(p).decode() for p in payloads], pa.string()),
                }
            )
            buffer = io.BytesIO()
            pq.write_table(table, buffer)
            modified = self._FIRST_MODIFIED + datetime.timedelta(minutes=index)
            self._files[f"{self._folder}/{index:04d}.parquet"] = (modified, buffer.getvalue())

    async def _ls(self, path: str, detail: bool = False, refresh: bool = False) -> list[Any]:
        if path.removeprefix("s3://") != self._folder:
            raise FileNotFoundError(path)
        return [{"Key": key, "type": "file", "LastModified": modified} for key, (modified, _) in self._files.items()]

    async def open_async(self, path: str, mode: str = "rb") -> "_StagedFile":
        return _StagedFile(self._files[path][1])

    async def _rm(self, path: Any, recursive: bool = False) -> None:
        return None

    async def _pipe_file(self, path: str, data: bytes) -> None:
        return None


class _StagedFile:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def __aenter__(self) -> "_StagedFile":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def read(self) -> bytes:
        return self._data


@contextlib.contextmanager
def _staged_webhook_files(inputs: SourceInputs, files: Sequence[Sequence[dict[str, Any]]]) -> Iterator[None]:
    """Turn the webhook on and serve the files from a fake webhook folder."""
    bucket = _StagedWebhookFiles(inputs, files)

    async def webhook_on(self: WebhookSourceManager, *args: Any, **kwargs: Any) -> bool:
        return True

    @contextlib.asynccontextmanager
    async def s3_client() -> AsyncIterator[_StagedWebhookFiles]:
        yield bucket

    with contextlib.ExitStack() as stack:
        for name in _REAL_WEBHOOK_CHECKS:
            stack.enter_context(_patched(WebhookSourceManager, name, webhook_on))
        stack.enter_context(_patched(webhook_s3, "aget_s3_client", s3_client))
        yield


@contextlib.contextmanager
def _patched(target: Any, name: str, value: Any) -> Iterator[None]:
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, original)


def _consume(emitted: Any, take: Callable[[Any], None]) -> None:
    """Hand each item to `take` as the source yields it, for a sync or an async iterable.

    The items pass one at a time rather than being collected first, so the cursor is committed
    between two rows exactly as the pipeline commits it.
    """
    if not hasattr(emitted, "__aiter__"):
        for item in emitted:
            take(item)
        return

    async def drain() -> None:
        async for item in emitted:
            take(item)

    asyncio.run(drain())
