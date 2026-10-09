import asyncio
import contextlib
from collections.abc import Callable, Iterator
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ResumableSource,
    SimpleSource,
    _BaseSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.fake_network import (
    RecordedRequest,
    RunStopped,
    fake_environment,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.inputs import source_inputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.responders import (
    Script,
    ScriptedResponder,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs


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
    raised: BaseException | None

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
    """

    def __init__(self, source: _BaseSource[Any], config: Any) -> None:
        self._source = source
        self._config = config

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
        with fake_environment(ScriptedResponder(script)) as network:
            built = source_inputs(schema_name, **inputs)
            saved: list[Any] = []
            committed: list[Any] = []
            rows: list[Any] = []
            items: list[Any] = []
            raised: BaseException | None = None

            with self._recording_saves(saved):
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

            return DriveResult(
                rows=rows,
                items=items,
                requests=list(network.requests_log),
                saved_states=saved,
                committed_states=committed,
                raised=raised,
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


@contextlib.contextmanager
def _patched(target: type, name: str, value: Any) -> Iterator[None]:
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
