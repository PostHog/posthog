"""Remember which view rows a run already produced, so an unchanged row triggers only once.

A materialized view's incremental window is inclusive of the previous run's watermark, so the rows
on the boundary are recomputed and read again on every run without having changed. Each of those
rows reaches ``CDPProducer``, which is what starts a subscribed workflow or destination, so a
workflow that sends a message sends it again every sync period.

The producer already keys a view row's event id on row content alone, which makes an unchanged row
recognizable across runs. This store keeps the ids a view produced and suppresses the repeats.

The record is one Redis set per view, replaced on each run. It holds the ids this run produced plus
the ids this run suppressed, so a row that keeps coming back stays suppressed for as long as it
does, and a row that stops coming back drops out after one run.

Two runs of the same view can overlap, because the producer workflow is keyed on the job rather
than the view, and only same-schedule runs take ``ScheduleOverlapPolicy.SKIP``. Both then read the
same record and the later commit replaces the earlier one's ids. That costs a repeat trigger on a
later run, which is the behavior this store removes, and never a dropped one: an id is only ever
suppressed because an earlier run produced it. Serializing the load through the commit would mean
holding a lock across the whole produce loop, which runs for as long as the rows take to reach
Kafka, and a lock that expires under that would give the same interleaving with more to go wrong.
"""

import asyncio
from itertools import batched
from typing import Any

from prometheus_client import Counter
from structlog.types import FilteringBoundLogger

from posthog.redis import get_async_client

CDP_PRODUCER_ROWS_SUPPRESSED_TOTAL = Counter(
    "warehouse_cdp_producer_rows_suppressed_total",
    "Warehouse view rows not produced because a previous run produced the identical row",
    labelnames=["team_id"],
)

# A row only has to stay remembered from one run of its view to the next. The longest cadence a view
# can take is 30day, which runs monthly, so two runs can be 31 days apart plus schedule jitter. 35
# days covers that with room for a run that is late or retried. Each run replaces the record, so a
# longer lifetime only keeps the record of a view that stopped running for longer.
EMITTED_ROWS_TTL_SECONDS = 35 * 24 * 60 * 60

# Above this, the run stops recording, and the rows it did not record trigger again on the next run.
# The record keeps the first rows a run sees, so a view that stays past the limit repeats the rows
# past it on every run. Suppression is best effort, like the rest of this path, and a view large
# enough to pass the limit must not be able to grow one Redis key without bound.
MAX_TRACKED_ROWS = 200_000

# Kept well under Redis' argument limit, so a large run cannot build a command the server rejects.
_WRITE_CHUNK_SIZE = 1_000


def emitted_rows_key(team_id: int, saved_query_id: str) -> str:
    # The braces are a Redis Cluster hash tag. commit() renames a scratch key onto this one inside a
    # transaction, and on a cluster that fails with CROSSSLOT unless both keys hash to the same slot.
    return f"cdp_produced_view_rows:{{{team_id}:{saved_query_id}}}"


class EmittedRowStore:
    """The event ids a view produced on its previous run.

    Fail-open by design: a Redis problem disables suppression for the run, which costs a repeated
    trigger. Failing closed would drop a real one.
    """

    def __init__(self, key: str | None, logger: FilteringBoundLogger) -> None:
        self._key = key
        self._logger = logger
        self._previous: set[str] = set()
        self._current: set[str] = set()
        self._pending_deliveries: list[tuple[str, asyncio.Future[Any]]] = []
        self._enabled = key is not None
        self._at_limit = False

    async def load(self) -> None:
        if not self._enabled:
            return

        try:
            members = await get_async_client().smembers(self._key)
            self._previous = {member.decode() if isinstance(member, bytes) else member for member in members}
        except Exception as e:
            self._enabled = False
            await self._logger.awarning(f"Could not read produced view rows; not suppressing repeats this run: {e}")

    def is_repeat(self, event_id: str) -> bool:
        """Whether a previous run already produced this exact row.

        A repeat is recorded now: an earlier run delivered it, and keeping it in the record is what
        holds a row on the boundary suppressed across many runs. A row that is not a repeat is
        recorded only once Kafka confirms its delivery, through record_on_delivery, so a row no
        subscriber received is not remembered as delivered.
        """
        if not self._enabled:
            return False

        if event_id in self._previous:
            self._track(event_id)
            return True

        return False

    def record_on_delivery(self, event_id: str, delivery: asyncio.Future[Any]) -> None:
        """Hold a produced row until record_delivered reads its delivery result.

        produce() only queues the row. Kafka reports a failed delivery later, on this future, so a
        row recorded at produce time could be one that no subscriber received.
        """
        if not self._enabled:
            return

        self._pending_deliveries.append((event_id, delivery))

    def record_settled(self) -> None:
        """Record the held rows whose delivery Kafka confirmed so far, and keep the rest held.

        Call it between the batches of a file. A delivered row's future keeps the row's serialized
        payload, and one file can hold millions of rows, so holding every future until the file is
        flushed can run the worker out of memory. A row still in flight stays held for a later call.
        """
        in_flight: list[tuple[str, asyncio.Future[Any]]] = []
        for event_id, delivery in self._pending_deliveries:
            if not delivery.done():
                in_flight.append((event_id, delivery))
            elif not delivery.cancelled() and delivery.exception() is None:
                self.record_produced(event_id)
        self._pending_deliveries = in_flight

    def record_delivered(self) -> None:
        """Record the held rows whose delivery Kafka confirmed, and drop the rest.

        Call it after a file's rows are flushed, or after the file fails. A row with no confirmed
        delivery at that point is not recorded, so the worst case is one more trigger next run.
        """
        self.record_settled()
        self._pending_deliveries.clear()

    def record_produced(self, event_id: str) -> None:
        """Remember a row this run delivered."""
        if not self._enabled:
            return

        self._track(event_id)

    def _track(self, event_id: str) -> None:
        if len(self._current) < MAX_TRACKED_ROWS:
            self._current.add(event_id)
        else:
            self._at_limit = True

    async def commit(self) -> None:
        """Replace the record with what this run saw.

        Written to a scratch key and renamed, so a failure part way through leaves the previous
        run's record in place instead of a half-written one.
        """
        if not self._enabled:
            return

        if self._at_limit:
            await self._logger.awarning(
                f"More than {MAX_TRACKED_ROWS} view rows in one run; rows past that may trigger again next run"
            )

        try:
            client = get_async_client()
            if not self._current:
                await client.delete(self._key)
                return

            scratch_key = f"{self._key}:writing"
            # One flush rather than a round trip per chunk, which at the tracked-row limit would be
            # hundreds of them at the end of every run.
            pipeline = client.pipeline(transaction=True)
            pipeline.delete(scratch_key)
            for chunk in batched(self._current, _WRITE_CHUNK_SIZE, strict=False):
                pipeline.sadd(scratch_key, *chunk)
            pipeline.expire(scratch_key, EMITTED_ROWS_TTL_SECONDS)
            pipeline.rename(scratch_key, self._key)
            await pipeline.execute()
        except Exception as e:
            await self._logger.awarning(f"Could not record produced view rows; repeats may not be suppressed: {e}")
