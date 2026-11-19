from collections.abc import AsyncIterable
from contextlib import AbstractAsyncContextManager, nullcontext

import pyarrow as pa

from products.warehouse_destinations.backend.facade.contracts import (
    Destination,
    DestinationConnection,
    DestinationLogger,
    PreparedTarget,
    TableTarget,
    WriteOutcome,
)


class FakeDestination:
    destination_type = "Fake"

    def __init__(self, connection: DestinationConnection, *, logger: DestinationLogger | None = None) -> None:
        self.connection = connection
        self.logger = logger

    def connect(self) -> AbstractAsyncContextManager[None]:
        return nullcontext()

    async def prepare(self, target: TableTarget) -> PreparedTarget:
        return PreparedTarget(target=target, write_into=(*target.namespace, target.table_name), existing_columns=())

    async def write(
        self, prepared: PreparedTarget, batches: AsyncIterable[pa.RecordBatch], *, batch_key: str | None = None
    ) -> WriteOutcome:
        return WriteOutcome(rows_written=0, bytes_written=0)

    async def commit(self, prepared: PreparedTarget) -> None:
        return None

    async def abort(self, prepared: PreparedTarget) -> None:
        return None


def build_fake_destination(
    connection: DestinationConnection, *, logger: DestinationLogger | None = None
) -> Destination:
    return FakeDestination(connection, logger=logger)


NOT_CALLABLE = "not a factory"
