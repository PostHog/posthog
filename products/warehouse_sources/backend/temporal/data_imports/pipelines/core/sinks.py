from collections.abc import Sequence
from typing import Protocol

import pyarrow as pa
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import schema_binding
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer import CDPProducer
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.person_property_row_sink import (
    PersonPropertyRowSink,
)


class ChunkSink(Protocol):
    """A gated tap on the pipeline write loop.

    A sink observes every chunk the pipeline writes without being part of the write itself:
    it is cleared once at run start, then handed each chunk in write order. `should_run` is
    the sink's own gate (e.g. "does any enabled HogFunction reference this table?") — the
    loop consults it before every operation so a gated-off sink costs nothing beyond the
    (cached) gate check, and a sink failure fails the sync like any other write-loop error.
    """

    async def should_run(self) -> bool: ...

    async def clear(self) -> None: ...

    async def stage_chunk(self, chunk: int, table: pa.Table) -> None: ...


class PipelineSinks:
    """The pipeline's chunk sinks, iterated at one call site per moment (clear / per-chunk).

    `cdp_producer` is also exposed directly: its gate feeds `PipelineResult.should_trigger_cdp_producer`,
    which the workflow reads to start the post-sync Kafka producer job — a post-run concern
    outside the chunk-sink contract.
    """

    def __init__(self, sinks: Sequence[ChunkSink], cdp_producer: CDPProducer) -> None:
        self.all: list[ChunkSink] = list(sinks)
        self.cdp_producer = cdp_producer

    async def clear(self) -> None:
        for sink in self.all:
            if await sink.should_run():
                await sink.clear()

    async def stage_chunk(self, chunk: int, table: pa.Table) -> None:
        for sink in self.all:
            if await sink.should_run():
                await sink.stage_chunk(chunk, table)


def build_pipeline_sinks(
    *,
    team_id: int,
    schema_id: str,
    job_id: str,
    logger: FilteringBoundLogger,
    is_incremental: bool,
) -> PipelineSinks:
    """The single wiring point for every chunk sink, shared by the v2 and v3 pipelines.

    A new publisher becomes one entry here instead of new constructor blocks and call
    sites in each pipeline.
    """
    cdp_producer = CDPProducer.for_source(team_id=team_id, schema_id=schema_id, job_id=job_id, logger=logger)
    person_property_sink = PersonPropertyRowSink(
        team_id=team_id,
        binding=schema_binding(schema_id),
        job_id=job_id,
        logger=logger,
        is_incremental=is_incremental,
    )
    return PipelineSinks([cdp_producer, person_property_sink], cdp_producer)
