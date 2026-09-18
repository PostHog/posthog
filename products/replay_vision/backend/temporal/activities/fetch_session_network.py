"""Fetch a session's captured network requests from the recording blocks and stash them in Redis."""

import time
import asyncio

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.recordings.errors import RecordingApiConfigurationError
from posthog.session_recordings.recordings.recording_api_client import recording_api_client
from posthog.session_recordings.session_recording_v2_service import RecordingBlock, list_blocks_async

from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.network_capture import NetworkCollector, SessionNetworkPayload
from products.replay_vision.backend.temporal.state import (
    StateActivitiesEnum,
    get_redis_state_client,
    store_data_in_redis,
)
from products.replay_vision.backend.temporal.types import FetchSessionNetworkInputs

logger = structlog.get_logger(__name__)

# The rasterizer is reading the same blocks for the video render, so keep one scan from adding a burst of
# load to the recording API.
_BLOCK_CONCURRENCY = 4

# Matches the rasterizer's `maxRecordingCompressedBytes`
# (nodejs/src/session-replay/recording-rasterizer/config.ts), which is sized against real recordings. A
# lower figure here skipped the median recording: on 2026-09-17 the skipped sessions had a median of 88
# MiB compressed and a 95th percentile of 380 MiB.
_MAX_COMPRESSED_BYTES = 512 * 1024 * 1024

# What the read is really bounded by. Memory is already bounded by the batch, so the risk of a long
# listing is the activity's own 2 minute timeout, which the server enforces from outside and which no
# block count predicts. Stop at the deadline and report what was read instead of refusing the session.
# The deadline bounds the batch in flight as well as the next one: a request carries its own 30 second
# timeout, so checking only between batches would let the read run to 90 seconds.
_READ_BUDGET_SECONDS = 60.0

# Bytes allowed in flight at once. Concurrency alone does not bound memory, because a block can be large:
# on 2026-09-17 the median recording averaged 368 KiB per block, the 95th percentile 2 MiB, and the worst
# 37 MiB. Four of those decompressed together would threaten the worker's memory limit.
_MAX_BATCH_COMPRESSED_BYTES = 16 * 1024 * 1024


@activity.defn
@track_activity()
async def fetch_session_network_activity(inputs: FetchSessionNetworkInputs) -> None:
    """Decode the session's network requests into Redis; idempotent, and never fails the scan.

    Network data is a side input: it sharpens a finding when it is there, and the scan is still valid
    without it. So every failure path stores an empty payload instead of raising, which also stops a
    retry loop from re-reading a large recording. The one exception is a missing recording-api
    setting, which is a fault of the whole deployment and has to stay visible.
    """
    try:
        redis_client, redis_key = get_redis_state_client(
            label=StateActivitiesEnum.SESSION_NETWORK,
            state_id=str(inputs.observation_id),
        )
        if await redis_client.exists(redis_key):
            return
        payload = await _load_payload(inputs.team_id, inputs.session_id)
    except RecordingApiConfigurationError as exc:
        # A missing setting stops every session, not this one, so absorbing it here would bury a
        # deployment fault in one warning per scan. Fail the activity instead: `_optional` in the
        # workflow keeps the scan running, and the failure reaches Temporal and the activity metric
        # under a named cause. Non-retryable because no further attempt can find the setting.
        raise ApplicationError(str(exc), type="RecordingApiConfigurationError", non_retryable=True) from exc
    except Exception:
        logger.warning(
            "replay_vision.fetch_network.failed",
            session_id=inputs.session_id,
            team_id=inputs.team_id,
            exc_info=True,
        )
        return

    try:
        await store_data_in_redis(redis_client, redis_key, payload.model_dump_json())
    except Exception:
        # Raising here would retry, and on the last attempt fail the scan. A missing key reads as
        # "no network data", which the scan already handles.
        logger.warning(
            "replay_vision.fetch_network.store_failed",
            session_id=inputs.session_id,
            team_id=inputs.team_id,
            exc_info=True,
        )


async def _load_payload(team_id: int, session_id: str) -> SessionNetworkPayload:
    recording = await sync_to_async(_build_recording)(team_id, session_id)
    blocks = await list_blocks_async(recording)
    if not blocks:
        return SessionNetworkPayload()

    compressed_bytes = sum(max(0, block.end_byte - block.start_byte) for block in blocks)
    if compressed_bytes > _MAX_COMPRESSED_BYTES:
        logger.info(
            "replay_vision.fetch_network.skipped_large_recording",
            session_id=session_id,
            team_id=team_id,
            block_count=len(blocks),
            compressed_bytes=compressed_bytes,
        )
        # Partial rather than empty: the scan must not read "nothing failed" from a recording never read.
        return SessionNetworkPayload(partial=True)

    return await _collect(blocks, session_id=session_id, team_id=team_id)


def _build_recording(team_id: int, session_id: str) -> SessionRecording:
    """The block listing keys off `session_id` and `team_id` only, so an unsaved instance is enough."""
    return SessionRecording(session_id=session_id, team_id=team_id)


def _next_batch(blocks: list[RecordingBlock], start: int) -> list[RecordingBlock]:
    """The blocks to fetch together: at most `_BLOCK_CONCURRENCY`, and at most `_MAX_BATCH_COMPRESSED_BYTES`.

    A single block larger than the byte budget goes on its own rather than being skipped, so a recording
    with one huge block is still read.
    """
    batch: list[RecordingBlock] = []
    total = 0
    for block in blocks[start : start + _BLOCK_CONCURRENCY]:
        size = max(0, block.end_byte - block.start_byte)
        if batch and total + size > _MAX_BATCH_COMPRESSED_BYTES:
            break
        batch.append(block)
        total += size
    return batch


def _log_budget_spent(session_id: str, team_id: int, blocks_read: int, block_count: int) -> None:
    logger.info(
        "replay_vision.fetch_network.read_budget_spent",
        session_id=session_id,
        team_id=team_id,
        blocks_read=blocks_read,
        block_count=block_count,
    )


async def _collect(blocks: list[RecordingBlock], *, session_id: str, team_id: int) -> SessionNetworkPayload:
    """Fetch the blocks a batch at a time and decode each batch before fetching the next.

    Peak memory stays at one batch rather than the whole decompressed session, whose size the block
    count does not bound. Fetching stops early once enough requests are kept.

    The recording API decrypts transparently, so an encrypted session needs no handling here. A block
    that fails to fetch contributes nothing rather than losing the whole session.
    """
    collector = NetworkCollector()
    partial = False
    deadline = time.monotonic() + _READ_BUDGET_SECONDS

    async with recording_api_client() as client:

        async def fetch(block: RecordingBlock) -> list[str] | None:
            try:
                content = await client.fetch_block(
                    block.key,
                    block.start_byte,
                    block.end_byte,
                    session_id,
                    team_id,
                    decompress=True,
                )
            except Exception:
                logger.warning(
                    "replay_vision.fetch_network.block_failed",
                    session_id=session_id,
                    team_id=team_id,
                    exc_info=True,
                )
                return None
            return content.decode("utf-8", errors="replace").splitlines()

        index = 0
        while index < len(blocks):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                partial = True
                _log_budget_spent(session_id, team_id, index, len(blocks))
                break
            batch = _next_batch(blocks, index)
            index += len(batch)
            tasks = [asyncio.create_task(fetch(block)) for block in batch]
            # `wait` rather than `wait_for`: a timeout must not discard the blocks of this batch that
            # already came back, which is the partial result the caller is promised.
            done, pending = await asyncio.wait(tasks, timeout=remaining)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            # Batch order, not completion order, so the same recording yields the same payload.
            for task in tasks:
                if task not in done:
                    continue
                block_lines = task.result()
                if block_lines is None:
                    partial = True
                    continue
                collector.feed(block_lines)
            if pending:
                # Out of time mid-batch. What was read still helps; `partial` stops the scan reading the
                # rest of the session as "nothing failed here".
                partial = True
                _log_budget_spent(session_id, team_id, index - len(batch), len(blocks))
                break
            if collector.full:
                break

    return collector.finish(partial=partial)
