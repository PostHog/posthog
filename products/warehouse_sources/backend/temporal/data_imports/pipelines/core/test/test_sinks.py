import pytest
from unittest.mock import AsyncMock, MagicMock

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.sinks import PipelineSinks


def _sink(*, gated_on: bool) -> MagicMock:
    return MagicMock(
        should_run=AsyncMock(return_value=gated_on),
        clear=AsyncMock(),
        stage_chunk=AsyncMock(),
    )


class TestPipelineSinks:
    @parameterized.expand(
        [
            # A gated-off sink must cost nothing beyond its gate check: staging to it would
            # write S3 chunks (or produce Kafka rows downstream) for a table no consumer wants.
            # A gated-on sink must receive the clear and every chunk, or its consumer silently
            # reads stale/partial data.
            ("gated_on", True),
            ("gated_off", False),
        ]
    )
    @pytest.mark.asyncio
    async def test_gate_is_consulted_per_operation(self, _name: str, gated_on: bool) -> None:
        sink = _sink(gated_on=gated_on)
        sinks = PipelineSinks([sink], cdp_producer=MagicMock())
        table = pa.table({"id": [1]})

        await sinks.clear()
        await sinks.stage_chunk(0, table)
        await sinks.stage_chunk(1, table)

        if gated_on:
            sink.clear.assert_awaited_once()
            assert [c.args for c in sink.stage_chunk.await_args_list] == [(0, table), (1, table)]
        else:
            sink.clear.assert_not_awaited()
            sink.stage_chunk.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_one_sinks_gate_does_not_gate_the_others(self) -> None:
        gated_off, gated_on = _sink(gated_on=False), _sink(gated_on=True)
        sinks = PipelineSinks([gated_off, gated_on], cdp_producer=MagicMock())

        await sinks.stage_chunk(0, pa.table({"id": [1]}))

        gated_off.stage_chunk.assert_not_awaited()
        gated_on.stage_chunk.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sink_failure_propagates(self) -> None:
        # A sink failure must fail the sync like any other write-loop error. Swallowing it here
        # would let a sync report success while its consumer's staged data is silently missing —
        # an incremental sync never re-stages those rows until they change again.
        sink = _sink(gated_on=True)
        sink.stage_chunk.side_effect = RuntimeError("staging blew up")
        sinks = PipelineSinks([sink], cdp_producer=MagicMock())

        with pytest.raises(RuntimeError, match="staging blew up"):
            await sinks.stage_chunk(0, pa.table({"id": [1]}))
